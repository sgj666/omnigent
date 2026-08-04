from __future__ import annotations

import json

import pytest
from omnigent_feishu.protocol import FeishuMessage
from omnigent_feishu.router import FeishuRouter
from omnigent_feishu.store import FeishuStore


class FakeCore:
    def __init__(self) -> None:
        self.calls = []

    async def create_run(self, command):
        self.calls.append(command.payload())
        return {"id": "run-1", "status": "running"}


@pytest.mark.asyncio
async def test_restart_dedup_routes_only_through_core_http_contract(tmp_path) -> None:
    path = tmp_path / "provider.db"
    store = FeishuStore(path)
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.bind_thread(
        installation_id=installation.id,
        chat_id="chat",
        thread_id=None,
        agent_id="ag_polly",
        workspace_id="ws_multi",
    )
    core = FakeCore()
    event = FeishuMessage("evt", "chat", None, "implement", "ou_sender")
    first = await FeishuRouter(store, core, action_secret="secret").route(event, installation.id)
    restarted = FeishuStore(path)
    await restarted.initialize()
    second = await FeishuRouter(restarted, core, action_secret="secret").route(
        event, installation.id
    )
    assert first.run_id == second.run_id == "run-1"
    assert second.duplicate
    assert len(core.calls) == 1
    assert core.calls[0] == {
        "agent_id": "ag_polly",
        "workspace_id": "ws_multi",
        "input": "implement",
        "source": "integration:feishu",
        "source_event_id": "feishu:evt",
        "host_id": None,
        "execution_mode": "auto",
    }
    columns = await restarted.table_columns()
    forbidden = {"team_id", "coordinator_id", "agent_profile_id", "transcript", "bundle_yaml"}
    assert forbidden.isdisjoint(set().union(*columns.values()))


@pytest.mark.asyncio
async def test_notification_retry_survives_restart(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db", clock=lambda: 100)
    await store.initialize()
    note = await store.enqueue_notification(
        installation_id="fi", run_id="run", event_id="done:run", payload={"ok": True}
    )
    await store.retry_notification(note.id, "network secret must not be copied")
    restarted = FeishuStore(store.path, clock=lambda: 200)
    due = await restarted.due_notifications()
    assert due[0].status == "retrying"
    assert json.loads(due[0].payload) == {"ok": True}
