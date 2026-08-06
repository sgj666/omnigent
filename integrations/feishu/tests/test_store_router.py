from __future__ import annotations

import json

import pytest
from omnigent_feishu.cards import action_value
from omnigent_feishu.protocol import FeishuCardAction, FeishuMenuAction, FeishuMessage
from omnigent_feishu.router import FeishuRouter, FeishuRoutingError
from omnigent_feishu.store import FeishuStore


class FakeCore:
    def __init__(self) -> None:
        self.calls = []

    async def create_session(self, command):
        self.calls.append(command.payload())
        return {"id": "session-1", "status": "launching"}

    async def send_session_input(self, session_id, text):
        self.calls.append({"session_id": session_id, "text": text})
        return {"ok": True}

    async def stop_session(self, session_id):
        self.calls.append({"stop_session_id": session_id})
        return {"ok": True}

    async def get_session(self, session_id):
        self.calls.append({"get_session_id": session_id})
        return {"status": "completed"}

    async def get_session_items(self, session_id):
        self.calls.append({"get_session_items_id": session_id})
        return {"data": []}

    async def list_hosts(self):
        return {
            "hosts": [
                {"host_id": "host-1", "name": "Local Mac", "status": "online"},
                {"host_id": "host-2", "name": "Build Mac", "status": "online"},
            ]
        }


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
        workspace_id="/Users/test/workspace",
        host_id="host-1",
    )
    core = FakeCore()
    event = FeishuMessage("evt", "chat", None, "implement", "ou_sender")
    first = await FeishuRouter(store, core, action_secret="secret").route(event, installation.id)
    restarted = FeishuStore(path)
    await restarted.initialize()
    second = await FeishuRouter(restarted, core, action_secret="secret").route(
        event, installation.id
    )
    assert first.run_id == second.run_id == "session-1"
    assert second.duplicate
    assert len(core.calls) == 2
    assert core.calls[0] == {
        "agent_id": "ag_polly",
        "workspace": "/Users/test/workspace",
        "host_id": "host-1",
    }
    assert core.calls[1] == {"session_id": "session-1", "text": "implement"}
    columns = await restarted.table_columns()
    forbidden = {"team_id", "coordinator_id", "agent_profile_id", "transcript", "bundle_yaml"}
    assert forbidden.isdisjoint(set().union(*columns.values()))


@pytest.mark.asyncio
async def test_greeting_returns_setup_guide_without_calling_core(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.connect_installation(
        installation.id,
        app_id="app",
        app_secret_ciphertext="ciphertext",
        installer_open_id="installer",
        bot_open_id="bot",
    )
    core = FakeCore()

    result = await FeishuRouter(store, core, action_secret="secret").route(
        FeishuMessage("evt", "chat", None, "hello", "ou_sender"), installation.id
    )

    assert result.run_id is None
    assert isinstance(result.payload, dict)
    assert result.payload["message"] is None
    assert result.payload["guide_card"]["header"]["title"]["content"] == "Omnigent · 开始工作"
    assert core.calls == []


@pytest.mark.asyncio
async def test_group_members_continue_the_same_chat_session(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.connect_installation(
        installation.id,
        app_id="app",
        app_secret_ciphertext="ciphertext",
        installer_open_id="installer",
        bot_open_id="bot",
    )
    await store.set_installation_workspace_scope(
        installation.id, workspace="/Users/test/workspace", host_id="host-1"
    )
    core = FakeCore()
    router = FeishuRouter(store, core, action_secret="secret")

    first = await router.route(
        FeishuMessage("evt-one", "group-chat", None, "first task", "ou_alice"), installation.id
    )
    second = await router.route(
        FeishuMessage("evt-two", "group-chat", None, "continue it", "ou_bob"), installation.id
    )

    assert first.run_id == second.run_id == "session-1"
    assert core.calls == [
        {"agent_id": "ag_polly", "workspace": "/Users/test/workspace", "host_id": "host-1"},
        {"session_id": "session-1", "text": "first task"},
        {"get_session_id": "session-1"},
        {"get_session_items_id": "session-1"},
        {"session_id": "session-1", "text": "continue it"},
    ]


@pytest.mark.asyncio
async def test_greeting_preserves_default_workspace_without_starting_a_run(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.connect_installation(
        installation.id,
        app_id="app",
        app_secret_ciphertext="ciphertext",
        installer_open_id="installer",
        bot_open_id="bot",
    )
    await store.set_installation_workspace_scope(
        installation.id, workspace="/Users/test/container", host_id="host-1"
    )
    core = FakeCore()

    result = await FeishuRouter(store, core, action_secret="secret").route(
        FeishuMessage("evt", "chat", None, "hello", "ou_sender"), installation.id
    )

    assert result.run_id is None
    assert core.calls == []
    assert "/Users/test/container" in result.payload["guide_card"]["elements"][2]["content"]


@pytest.mark.asyncio
async def test_new_command_stops_and_creates_a_fresh_bound_session(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    binding = await store.bind_thread(
        installation_id=installation.id,
        chat_id="chat",
        thread_id=None,
        agent_id="ag_polly",
        workspace_id="/Users/test/workspace",
        host_id="host-1",
    )
    await store.set_binding_run(binding.id, "session-old")
    await store.set_binding_root_session(binding.id, "session-old")
    core = FakeCore()

    result = await FeishuRouter(store, core, action_secret="secret").route(
        FeishuMessage("evt-new", "chat", None, "/new", "ou_sender"), installation.id
    )

    assert isinstance(result.payload, dict)
    assert result.payload["guide_card"]["header"]["title"]["content"] == "Omnigent · 开始工作"
    assert core.calls == [
        {"stop_session_id": "session-old"},
        {"agent_id": "ag_polly", "workspace": "/Users/test/workspace", "host_id": "host-1"},
    ]
    assert await store.get_binding_root_session(binding.id) == "session-1"


@pytest.mark.asyncio
async def test_new_session_card_creates_a_fresh_core_session_immediately(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    binding = await store.bind_thread(
        installation_id=installation.id,
        chat_id="chat",
        thread_id=None,
        agent_id="ag_polly",
        workspace_id="/Users/test/workspace",
        host_id="host-1",
    )
    core = FakeCore()
    value = action_value(
        "new_session", signing_secret="secret", nonce="new-session", agent_id="ag_polly"
    )

    result = await FeishuRouter(store, core, action_secret="secret").route_action(
        FeishuCardAction(
            "evt-new-card", "new_session", "new-session", "chat", None, "ou_sender", value
        ),
        installation.id,
    )

    assert result.run_id == "session-1"
    assert core.calls == [
        {"agent_id": "ag_polly", "workspace": "/Users/test/workspace", "host_id": "host-1"}
    ]
    assert await store.get_binding_root_session(binding.id) == "session-1"


@pytest.mark.asyncio
async def test_task_text_after_greeting_creates_a_run(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.bind_thread(
        installation_id=installation.id,
        chat_id="chat",
        thread_id=None,
        agent_id="ag_polly",
        workspace_id="/Users/test/workspace",
        host_id="host-1",
    )
    core = FakeCore()

    result = await FeishuRouter(store, core, action_secret="secret").route(
        FeishuMessage("evt-task", "chat", None, "修复登录页的报错", "ou_sender"), installation.id
    )

    assert result.run_id == "session-1"
    assert core.calls == [
        {"agent_id": "ag_polly", "workspace": "/Users/test/workspace", "host_id": "host-1"},
        {"session_id": "session-1", "text": "修复登录页的报错"},
    ]


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


@pytest.mark.asyncio
async def test_surface_profile_and_workspace_allow_list_are_agent_scoped(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db", clock=lambda: 100)
    await store.initialize()
    await store.set_agent_surface_profile(
        "ag-one",
        details_base_url="https://one.example",
        actions=["quick_commands", "switch_workspace"],
    )
    await store.set_agent_default_scope("ag-one", workspace="/Users/me/one", host_id="host-1")
    await store.set_agent_default_scope("ag-two", workspace="/Users/me/two", host_id="host-2")

    assert await store.get_agent_surface_profile("ag-one") == {
        "details_enabled": True,
        "details_base_url": "https://one.example",
        "actions": ["quick_commands", "switch_workspace"],
        "updated_at": 100,
    }
    assert await store.get_agent_surface_profile("ag-two") is None
    assert await store.list_agent_workspace_scopes("ag-one") == [("/Users/me/one", "host-1")]
    assert await store.list_agent_workspace_scopes("ag-two") == [("/Users/me/two", "host-2")]


@pytest.mark.asyncio
async def test_workspace_card_switches_only_to_an_agent_authorized_directory(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    binding = await store.bind_thread(
        installation_id=installation.id,
        chat_id="chat",
        thread_id=None,
        agent_id="ag_polly",
        workspace_id="/Users/test/old",
        host_id="host-1",
    )
    await store.set_agent_default_scope("ag_polly", workspace="/Users/test/new", host_id="host-2")
    value = action_value(
        "switch_workspace",
        signing_secret="secret",
        nonce="switch",
        agent_id="ag_polly",
        workspace_id="/Users/test/new",
        host_id="host-2",
    )

    await FeishuRouter(store, FakeCore(), action_secret="secret").route_action(
        FeishuCardAction(
            "evt-switch", "switch_workspace", "switch", "chat", None, "ou_sender", value
        ),
        installation.id,
    )

    refreshed = await store.get_binding(installation.id, "chat", None)
    assert refreshed is not None
    assert refreshed.id == binding.id
    assert refreshed.workspace_id == "/Users/test/new"
    assert refreshed.host_id == "host-2"


@pytest.mark.asyncio
async def test_manage_devices_card_uses_the_core_hosts_contract(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.bind_thread(
        installation_id=installation.id,
        chat_id="chat",
        thread_id=None,
        agent_id="ag_polly",
        workspace_id="/Users/test/workspace",
        host_id="host-1",
    )
    value = action_value(
        "manage_devices", signing_secret="secret", nonce="devices", agent_id="ag_polly"
    )

    result = await FeishuRouter(store, FakeCore(), action_secret="secret").route_action(
        FeishuCardAction(
            "evt-devices", "manage_devices", "devices", "chat", None, "ou_sender", value
        ),
        installation.id,
    )

    assert isinstance(result.payload, dict)
    actions = result.payload["guide_card"]["elements"][1]["actions"]
    assert [action["text"]["content"] for action in actions] == [
        "🖥️ Local Mac",
        "🖥️ Build Mac",
    ]


@pytest.mark.asyncio
async def test_bot_menu_event_routes_to_the_p2p_agent_binding_once(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.connect_installation(
        installation.id,
        app_id="app",
        app_secret_ciphertext="ciphertext",
        installer_open_id="ou_sender",
        bot_open_id="bot",
    )
    await store.set_installation_workspace_scope(
        installation.id, workspace="/Users/test/workspace", host_id="host-1"
    )
    await store.set_agent_surface_profile(
        "ag_polly",
        details_base_url="https://omnigent.example",
        actions=["quick_commands"],
    )
    core = FakeCore()
    router = FeishuRouter(store, core, action_secret="secret")
    await router.route(
        FeishuMessage(
            "evt-hello",
            "p2p-chat",
            None,
            "hello",
            "ou_sender",
            chat_type="p2p",
        ),
        installation.id,
    )

    first = await router.route_menu_action(
        FeishuMenuAction("evt-menu", "session_new", "ou_sender"), installation.id
    )
    second = await router.route_menu_action(
        FeishuMenuAction("evt-menu", "session_new", "ou_sender"), installation.id
    )

    assert first.run_id == second.run_id == "session-1"
    assert second.duplicate
    assert core.calls == [
        {
            "agent_id": "ag_polly",
            "workspace": "/Users/test/workspace",
            "host_id": "host-1",
        }
    ]


@pytest.mark.asyncio
async def test_bot_menu_event_respects_agent_capability_switches(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    await store.initialize()
    installation = await store.create_pending_installation(
        agent_id="ag_polly", session="s", verification_uri="https://qr"
    )
    await store.connect_installation(
        installation.id,
        app_id="app",
        app_secret_ciphertext="ciphertext",
        installer_open_id="ou_sender",
        bot_open_id="bot",
    )
    await store.set_agent_surface_profile(
        "ag_polly",
        details_base_url="https://omnigent.example",
        actions=["help"],
    )
    router = FeishuRouter(store, FakeCore(), action_secret="secret")
    await router.route(
        FeishuMessage(
            "evt-hello",
            "p2p-chat",
            None,
            "hello",
            "ou_sender",
            chat_type="p2p",
        ),
        installation.id,
    )

    with pytest.raises(FeishuRoutingError, match="not enabled") as caught:
        await router.route_menu_action(
            FeishuMenuAction("evt-menu", "manage_devices", "ou_sender"), installation.id
        )

    assert caught.value.code == "action_disabled"
