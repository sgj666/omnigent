from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from omnigent_feishu.cards import APPROVAL_ACTIONS, PERSISTENT_ACTIONS
from omnigent_feishu.credentials import FeishuCredentialCipher
from omnigent_feishu.device_flow import (
    FeishuDeviceSession,
    FeishuPending,
    FeishuRegistration,
)
from omnigent_feishu.routes import create_feishu_router
from omnigent_feishu.store import FeishuStore
from omnigent_feishu.surface import BotSurfaceProvisioner


class _Adapter:
    async def receive(self, *_args, **_kwargs):
        raise AssertionError("webhook adapter was not called")


def _app(store: FeishuStore, device, *, surface=None) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_feishu_router(
            store,
            device,
            FeishuCredentialCipher("credential-secret"),
            _Adapter(),
            surface_provisioner=surface,
        )
    )
    return app


@pytest.mark.asyncio
async def test_pending_installation_survives_restart_with_complete_pairing_state(
    tmp_path,
) -> None:
    now = [100]

    class Device:
        def __init__(self) -> None:
            self.polls = 0
            self.restored: list[tuple[str, int]] = []

        async def begin(self):
            return FeishuDeviceSession(
                session="device-session",
                verification_uri_complete="https://pair.example/qr",
                interval=3,
                expires_in=120,
                verification_uri="https://pair.example",
                user_code="ABCD-EFGH",
            )

        def restore(self, session: str, interval: int) -> None:
            self.restored.append((session, interval))

        async def poll(self, _session: str):
            self.polls += 1
            return FeishuPending(3)

    path = tmp_path / "provider.db"
    first_store = FeishuStore(path, clock=lambda: now[0])
    await first_store.initialize()
    await first_store.set_agent_default_scope("ag", workspace="/tmp/workspace", host_id="local")
    first_device = Device()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(first_store, first_device)),
        base_url="http://feishu",
    ) as client:
        begun = (await client.post("/v1/agents/ag/feishu/installations")).json()

    expected = {
        "status": "pending",
        "session": "device-session",
        "verification_uri": "https://pair.example",
        "verification_uri_complete": "https://pair.example/qr",
        "qr_uri": "https://pair.example/qr",
        "user_code": "ABCD-EFGH",
        "interval": 3,
        "expires_at": 220,
        "expires_in": 120,
    }
    assert {key: begun.get(key) for key in expected} == expected

    restarted_store = FeishuStore(path, clock=lambda: now[0])
    await restarted_store.initialize()
    restarted_device = Device()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(restarted_store, restarted_device)),
        base_url="http://feishu",
    ) as client:
        status = (await client.get("/v1/agents/ag/feishu")).json()
        pending = (await client.get("/v1/agents/ag/feishu/installations/device-session")).json()

        now[0] = 221
        expired = (await client.get("/v1/agents/ag/feishu")).json()

    assert status["user_code"] == pending["user_code"] == "ABCD-EFGH"
    assert pending["expires_in"] == 120
    assert restarted_device.restored == [("device-session", 3)]
    assert restarted_device.polls == 1
    assert expired["status"] == "expired"
    assert expired["error"] == "expired"
    assert expired["expires_in"] == 0


@pytest.mark.asyncio
async def test_connected_poll_and_status_include_safe_metadata_and_current_binding(
    tmp_path,
) -> None:
    class Device:
        async def poll(self, _session: str):
            return FeishuRegistration(
                app_id="cli-safe",
                app_secret="super-secret",
                installer_open_id="ou_installer",
                bot={
                    "open_id": "ou_bot",
                    "app_name": "Omnigent Bot",
                    "avatar": {"avatar_origin": "https://img.example/bot.png"},
                    "tenant_access_token": "must-never-serialize",
                },
                tenant_key="tenant-safe",
                tenant_name="Example Tenant",
            )

    store = FeishuStore(tmp_path / "provider.db", clock=lambda: 100)
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag",
        session="device-session",
        verification_uri="https://pair.example/qr",
        interval=3,
        expires_in=120,
    )
    app = _app(store, Device())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://feishu"
    ) as client:
        connected = (await client.get("/v1/agents/ag/feishu/installations/device-session")).json()
        bound = (
            await client.put(
                "/v1/agents/ag/feishu/binding",
                json={
                    "installation_id": installation.id,
                    "chat_id": "oc_sensitive_chat",
                    "thread_id": "omt_sensitive_thread",
                    "workspace_id": "ws_multi",
                    "allowed_members": ["ou_member_one", "ou_member_two"],
                },
            )
        ).json()
        reloaded = (await client.get("/v1/agents/ag/feishu")).json()

    assert connected["tenant_key"] == reloaded["tenant_key"] == "tenant-safe"
    assert connected["tenant_name"] == "Example Tenant"
    assert connected["bot_open_id"] == "ou_bot"
    assert connected["bot_name"] == "Omnigent Bot"
    assert connected["bot_avatar_url"] == "https://img.example/bot.png"
    assert bound == reloaded["binding"]
    assert bound["chat_id"].startswith("chat_")
    assert bound["thread_id"].startswith("thread_")
    assert bound["allowed_member_count"] == 2
    assert bound["allowed_members"] != ["ou_member_one", "ou_member_two"]
    assert bound["workspace_id"] == "ws_multi"
    assert bound["workspace"] == {
        "id": "ws_multi",
        "href": "/v1/workspaces/ws_multi",
        "repositories_href": "/v1/workspaces/ws_multi/repositories",
    }
    serialized = json.dumps({"connected": connected, "reloaded": reloaded})
    assert "super-secret" not in serialized
    assert "must-never-serialize" not in serialized
    assert "app_secret_ciphertext" not in serialized


class _SurfaceClient:
    def __init__(self, *, card_fails: bool = False) -> None:
        self.card_fails = card_fails
        self.cards: set[tuple[str, str]] = set()

    def supports_menu(self, _installation_id: str) -> bool:
        return False

    def upsert_persistent_card(self, installation_id, profile_id, _card):
        if self.card_fails:
            raise RuntimeError("provider token=must-never-serialize")
        self.cards.add((installation_id, profile_id))


@pytest.mark.asyncio
async def test_surface_partial_retry_returns_stable_persistent_action_results(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db", clock=lambda: 10)
    await store.initialize()
    await store.import_installation(
        installation_id="fi",
        agent_id="ag",
        app_id="cli",
        app_secret_ciphertext="ciphertext",
        installer_open_id="ou",
        bot_open_id="bot",
        created_at=1,
    )
    surface_client = _SurfaceClient()
    provisioner = BotSurfaceProvisioner(
        surface_client,
        store=store,
        signing_secret="action-secret",
        clock=lambda: 10,
    )
    app = _app(store, object(), surface=provisioner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://feishu"
    ) as client:
        first = (await client.post("/v1/agents/ag/feishu/surface/reinitialize")).json()
        second = (await client.post("/v1/agents/ag/feishu/surface/reinitialize")).json()
        status = (await client.get("/v1/agents/ag/feishu/surface/status")).json()

    persistent_ids = [action for action, _label in PERSISTENT_ACTIONS]
    approval_ids = {action for action, _label in APPROVAL_ACTIONS}
    assert first["status"] == second["status"] == status["status"] == "partial"
    assert [action["action_id"] for action in first["actions"]] == persistent_ids
    assert not approval_ids.intersection(action["action_id"] for action in first["actions"])
    assert {action["status"] for action in first["actions"]} == {"provisioned"}
    assert all(action["label_key"].startswith("feishu.action.") for action in first["actions"])
    assert first["actions"] == second["actions"] == status["actions"]
    assert surface_client.cards == {("fi", "omnigent-agent")}


@pytest.mark.asyncio
async def test_surface_failure_returns_safe_per_action_errors(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db", clock=lambda: 10)
    await store.initialize()
    await store.import_installation(
        installation_id="fi",
        agent_id="ag",
        app_id="cli",
        app_secret_ciphertext="ciphertext",
        installer_open_id="ou",
        bot_open_id="bot",
        created_at=1,
    )
    provisioner = BotSurfaceProvisioner(
        _SurfaceClient(card_fails=True),
        store=store,
        signing_secret="action-secret",
        clock=lambda: 10,
    )
    app = _app(store, object(), surface=provisioner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://feishu"
    ) as client:
        failed = (await client.post("/v1/agents/ag/feishu/surface/reinitialize")).json()

    assert failed["status"] == "failed"
    assert {action["status"] for action in failed["actions"]} == {"failed"}
    assert {action["error"] for action in failed["actions"]} == {"surface provisioning failed"}
    assert "must-never-serialize" not in json.dumps(failed)
