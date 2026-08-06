from __future__ import annotations

import subprocess
import sys

import pytest
from omnigent_feishu.adapter import FeishuAdapter
from omnigent_feishu.config import FeishuConfig
from omnigent_feishu.store import FeishuStore
from omnigent_feishu.surface import BotSurfaceProvisioner
from pydantic import ValidationError


def test_config_requires_core_url_and_encryption_secrets(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))
    for name in (
        "OMNIGENT_SERVER_URL",
        "OMNIGENT_FEISHU_CREDENTIAL_KEY",
        "OMNIGENT_FEISHU_ACTION_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        FeishuConfig()


def test_module_help_is_available_after_extra_install() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "omnigent_feishu", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "standalone Omnigent Feishu" in result.stdout


class SurfaceClient:
    def __init__(self) -> None:
        self.resources: set[tuple[str, str]] = set()

    def supports_menu(self, _installation_id: str) -> bool:
        return False

    def upsert_persistent_card(self, installation_id, profile_id, _card):
        self.resources.add((installation_id, profile_id))


@pytest.mark.asyncio
async def test_surface_fallback_is_idempotent_across_store_restart(tmp_path) -> None:
    path = tmp_path / "provider.db"
    store = FeishuStore(path)
    await store.initialize()
    client = SurfaceClient()
    first = await BotSurfaceProvisioner(
        client, store=store, signing_secret="secret", clock=lambda: 1
    ).ensure("fi", agent_id="ag")
    restarted = FeishuStore(path)
    await restarted.initialize()
    second = await BotSurfaceProvisioner(
        client, store=restarted, signing_secret="secret", clock=lambda: 2
    ).ensure("fi", agent_id="ag")
    assert first.status == second.status == "partial"
    assert client.resources == {("fi", "omnigent-agent")}
    assert (await restarted.get_surface("fi"))["last_provisioned_at"] == 2


class FailingDelivery:
    async def send(self, _installation_id, _payload):
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_delivery_failure_is_retryable_provider_state_only(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db", clock=lambda: 1)
    await store.initialize()
    await store.enqueue_notification(
        installation_id="fi", run_id="run-completed", event_id="complete", payload={"x": 1}
    )
    adapter = FeishuAdapter(object(), store)  # type: ignore[arg-type]
    assert await adapter.deliver_due(FailingDelivery()) == 0
    notification = await store.get_notification_by_event("fi", "complete")
    assert notification is not None
    assert notification.status == "retrying"
