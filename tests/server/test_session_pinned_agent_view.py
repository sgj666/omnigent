"""Execution helpers must consume a Session's pinned Agent Bundle view."""

from __future__ import annotations

import io
import tarfile
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
import yaml

import omnigent.runtime as runtime
from omnigent.entities import Agent, Conversation
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.bundles import bundle_location, validate_agent_bundle
from omnigent.server.routes import hosts
from omnigent.server.routes import sessions as sessions_routes
from omnigent.server.routes._sessions import helpers
from omnigent.server.routes.sessions import routes_events, routes_hooks
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import (
    SqlAlchemyConversationStore,
)
from tests.server.helpers import build_agent_bundle, create_test_session


class _AgentStore:
    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.get_calls: list[str] = []

    def get(self, agent_id: str) -> Agent:
        self.get_calls.append(agent_id)
        return self.agent


class _AgentCache:
    def __init__(self, loaded_by_location: dict[str, object]) -> None:
        self.loaded_by_location = loaded_by_location
        self.load_calls: list[tuple[str, str]] = []

    def load(self, agent_id: str, bundle_location: str, **kwargs: object) -> object:
        del kwargs
        self.load_calls.append((agent_id, bundle_location))
        return self.loaded_by_location[bundle_location]


def _pinned_conversation(agent_id: str, location: str, digest: str) -> Conversation:
    return Conversation(
        id="3" * 32,
        created_at=1,
        updated_at=1,
        root_conversation_id="3" * 32,
        agent_id=agent_id,
        agent_bundle_version=1,
        agent_bundle_digest=digest,
        agent_bundle_location=location,
    )


def _deny_bash_policy(event: dict[str, Any]) -> dict[str, str]:
    """Deny Bash so a pinned guardrail is visible in an HTTP assertion."""
    data = event.get("data")
    if event.get("type") == "tool_call" and isinstance(data, dict):
        if data.get("name") == "Bash":
            return {"result": "DENY", "reason": "pinned policy"}
    return {"result": "ALLOW"}


def _bundle_with_inline_mcp(name: str) -> bytes:
    """Build a minimal config.yaml bundle with one MCP server."""
    config = {
        "spec_version": 1,
        "name": name,
        "executor": {"config": {"harness": "claude-sdk"}},
        "tools": {
            "mutable-only": {
                "type": "mcp",
                "transport": "http",
                "url": "https://example.com/mutable",
            }
        },
    }
    data = yaml.safe_dump(config, sort_keys=False).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="config.yaml")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_harness_and_policy_spec_helpers_load_pinned_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot harness and policy evaluation cannot drift to current Agent state."""
    agent_id = "1" * 32
    digest_a = "a" * 64
    location_a = f"{agent_id}/{digest_a}"
    location_b = f"{agent_id}/{'b' * 64}"
    conv = _pinned_conversation(agent_id, location_a, digest_a)
    current_agent = Agent(
        id=agent_id,
        created_at=1,
        name="mutable",
        version=2,
        bundle_location=location_b,
    )
    spec_a = validate_agent_bundle(build_agent_bundle(name="pinned"))
    spec_b = validate_agent_bundle(
        build_agent_bundle(
            name="current",
            executor={"type": "omnigent", "config": {"harness": "codex-native"}},
        )
    )
    cache = _AgentCache(
        {
            location_a: SimpleNamespace(spec=spec_a),
            location_b: SimpleNamespace(spec=spec_b),
        }
    )
    store = _AgentStore(current_agent)
    monkeypatch.setattr("omnigent.runtime._globals._agent_store", store)
    monkeypatch.setattr(runtime, "get_agent_cache", lambda: cache)
    monkeypatch.setattr(helpers, "get_agent_cache", lambda: cache)

    assert sessions_routes._resolve_harness(conv) == "claude-sdk"
    assert helpers._load_agent_spec_for_session_impl(conv, store) is spec_a
    assert cache.load_calls == [(agent_id, location_a), (agent_id, location_a)]


@pytest.mark.asyncio
async def test_compact_and_host_launch_helpers_load_pinned_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compaction, workspace gates, and launch harness all use the pinned spec."""
    agent_id = "1" * 32
    digest_a = "a" * 64
    location_a = f"{agent_id}/{digest_a}"
    location_b = f"{agent_id}/{'b' * 64}"
    conv = _pinned_conversation(agent_id, location_a, digest_a)
    current_agent = Agent(
        id=agent_id,
        created_at=1,
        name="mutable",
        version=2,
        bundle_location=location_b,
    )
    spec_a = validate_agent_bundle(build_agent_bundle(name="pinned"))
    spec_b = validate_agent_bundle(
        build_agent_bundle(
            name="current",
            executor={"type": "omnigent", "config": {"harness": "codex-native"}},
        )
    )
    loaded_a = SimpleNamespace(spec=spec_a)
    loaded_b = SimpleNamespace(spec=spec_b)
    loaded_a.spec.os_env = SimpleNamespace(cwd="/pinned")
    loaded_b.spec.os_env = SimpleNamespace(cwd="/current")
    cache = _AgentCache({location_a: loaded_a, location_b: loaded_b})
    store = _AgentStore(current_agent)
    compact_specs: list[object] = []

    async def _compact_conversation_now(**kwargs: Any) -> None:
        compact_specs.append(kwargs["spec"])

    monkeypatch.setattr(
        "omnigent.runtime.workflow.compact_conversation_now",
        _compact_conversation_now,
    )

    await helpers._run_compact_locked(conv.id, conv, store, cache)  # type: ignore[arg-type]
    assert await hosts._resolve_agent_spec_cwd(conv, store, cache) == "/pinned"  # type: ignore[arg-type]
    assert await hosts._resolve_agent_harness(conv, store, cache) == "claude-sdk"  # type: ignore[arg-type]
    assert compact_specs == [spec_a]
    assert cache.load_calls == [
        (agent_id, location_a),
        (agent_id, location_a),
        (agent_id, location_a),
    ]


@pytest.mark.asyncio
async def test_native_policy_hook_uses_pinned_guardrails_after_agent_update(
    client: httpx.AsyncClient,
    db_uri: str,
    tmp_path: Any,
) -> None:
    """Native hook policy evaluation cannot drift to mutable guardrails."""
    bundle_a = build_agent_bundle(
        name="pinned-hook-policy",
        guardrails={
            "policies": {
                "deny_bash": {
                    "type": "function",
                    "function": {
                        "path": ("tests.server.test_session_pinned_agent_view._deny_bash_policy")
                    },
                }
            }
        },
    )
    created = await client.post(
        "/v1/sessions",
        data={"metadata": "{}"},
        files={"bundle": ("agent.tar.gz", bundle_a, "application/gzip")},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    agent_id = created.json()["agent_id"]
    bundle_b = build_agent_bundle(name="pinned-hook-policy")
    location_b = bundle_location(agent_id, bundle_b)
    LocalArtifactStore(str(tmp_path / "artifacts")).put(location_b, bundle_b)
    updated = SqlAlchemyAgentStore(db_uri).update(agent_id, location_b)
    assert updated is not None and updated.version == 2

    response = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json={
            "event": {
                "type": "PHASE_TOOL_CALL",
                "data": {"name": "Bash", "input": {"command": "echo hi"}},
                "context": {},
            }
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "POLICY_ACTION_DENY"
    assert response.json()["reason"] == "pinned policy"


@pytest.mark.asyncio
async def test_native_policy_hook_rejects_partial_snapshot_before_policy_state(
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt hook sessions fail before Agent or policy-state reads."""
    session = await create_test_session(client, name="hook-partial-snapshot")
    session_id = session["id"]
    engine = sa.create_engine(db_uri)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE conversations SET agent_bundle_digest = NULL WHERE id = :id"),
                {"id": bytes.fromhex(session_id)},
            )
    finally:
        engine.dispose()
    side_effects: list[str] = []
    original_get = SqlAlchemyAgentStore.get

    def _get(store: SqlAlchemyAgentStore, agent_id: str):
        side_effects.append("agent")
        return original_get(store, agent_id)

    def _policy_state(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        side_effects.append("policy")
        return False

    monkeypatch.setattr(SqlAlchemyAgentStore, "get", _get)
    monkeypatch.setattr(routes_hooks, "any_policies_apply", _policy_state)

    response = await client.post(
        f"/v1/sessions/{session_id}/policies/evaluate",
        json={
            "event": {
                "type": "PHASE_TOOL_CALL",
                "data": {"name": "Read", "input": {}},
                "context": {},
            }
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert side_effects == []


@pytest.mark.asyncio
async def test_post_event_mcp_hint_uses_pinned_bundle(
    client: httpx.AsyncClient,
    db_uri: str,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner MCP hint comes from the Session snapshot, not mutable Agent."""
    session = await create_test_session(client, name="pinned-event-hint")
    session_id = session["id"]
    agent_id = session["agent_id"]
    bundle_b = _bundle_with_inline_mcp("pinned-event-hint")
    location_b = bundle_location(agent_id, bundle_b)
    LocalArtifactStore(str(tmp_path / "artifacts")).put(location_b, bundle_b)
    updated = SqlAlchemyAgentStore(db_uri).update(agent_id, location_b)
    assert updated is not None and updated.version == 2
    hints: list[bool] = []

    async def _runner_client(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return object()

    async def _relay(*args: object, **kwargs: object) -> None:
        del args, kwargs

    async def _dispatch(*args: object, **kwargs: object) -> object:
        del args
        hints.append(bool(kwargs["has_mcp_servers"]))
        return helpers._SessionEventDispatchResult(item_id="item_1", pending_id=None)

    monkeypatch.setattr(routes_events, "_get_runner_client", _runner_client)
    monkeypatch.setattr(routes_events, "_ensure_runner_relay_ready", _relay)
    monkeypatch.setattr(routes_events, "_dispatch_session_event_to_runner", _dispatch)

    response = await client.post(
        f"/v1/sessions/{session_id}/events",
        json={
            "type": "message",
            "data": {
                "role": "user",
                "content": [{"type": "input_text", "text": "go"}],
            },
        },
    )

    assert response.status_code == 202, response.text
    assert hints == [False]


@pytest.mark.asyncio
async def test_smart_routing_loads_pinned_parent_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smart-routing worker resolution loads the pinned parent bundle."""
    agent_id = "1" * 32
    digest_a = "a" * 64
    location_a = f"{agent_id}/{digest_a}"
    location_b = f"{agent_id}/{'b' * 64}"
    conv = _pinned_conversation(agent_id, location_a, digest_a)
    current_agent = Agent(
        id=agent_id,
        created_at=1,
        name="mutable",
        version=2,
        bundle_location=location_b,
    )
    spec_a = validate_agent_bundle(build_agent_bundle(name="pinned-router"))
    spec_b = validate_agent_bundle(build_agent_bundle(name="mutable-router"))
    cache = _AgentCache(
        {
            location_a: SimpleNamespace(spec=spec_a),
            location_b: SimpleNamespace(spec=spec_b),
        }
    )
    store = _AgentStore(current_agent)
    monkeypatch.setattr(helpers, "get_agent_cache", lambda: cache)
    monkeypatch.setattr(
        helpers,
        "get_caps",
        lambda: SimpleNamespace(routing_client=object()),
    )

    await helpers._handle_advise_models_mcp(
        "rpc_1",
        conv,
        {"tasks": []},
        store,  # type: ignore[arg-type]
    )

    assert cache.load_calls == [(agent_id, location_a)]


@pytest.mark.asyncio
async def test_smart_routing_rejects_partial_snapshot_before_routing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt smart-routing sessions fail before Agent or caps reads."""
    conv = Conversation(
        id="3" * 32,
        created_at=1,
        updated_at=1,
        root_conversation_id="3" * 32,
        agent_id="1" * 32,
        agent_bundle_version=1,
    )
    state_reads: list[str] = []

    class _Store:
        @staticmethod
        def get(agent_id: str) -> None:
            state_reads.append(agent_id)

    def _caps() -> object:
        state_reads.append("caps")
        return SimpleNamespace(routing_client=object())

    monkeypatch.setattr(helpers, "get_caps", _caps)

    with pytest.raises(OmnigentError) as exc_info:
        await helpers._handle_advise_models_mcp(
            "rpc_1",
            conv,
            {"tasks": []},
            _Store(),  # type: ignore[arg-type]
        )

    assert exc_info.value.code == ErrorCode.CONFLICT
    assert state_reads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_id", [None, "runner_online"], ids=["offline", "online"])
async def test_post_event_rejects_corrupt_snapshot_before_side_effects(
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    runner_id: str | None,
) -> None:
    """Both offline and online message paths fail before policy/status/item work."""
    session = await create_test_session(client, name=f"event-{runner_id or 'offline'}")
    session_id = session["id"]
    engine = sa.create_engine(db_uri)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE conversations SET agent_bundle_digest = NULL WHERE id = :session_id"
                ),
                {"session_id": bytes.fromhex(session_id)},
            )
    finally:
        engine.dispose()
    if runner_id is not None:
        assert SqlAlchemyConversationStore(db_uri).set_runner_id(session_id, runner_id)

    side_effects: list[str] = []

    async def _policy(*args: object, **kwargs: object) -> dict[str, str]:
        del args, kwargs
        side_effects.append("policy")
        return {"verdict": "deny", "reason": "recorded"}

    async def _persist(*args: object, **kwargs: object) -> None:
        del args, kwargs
        side_effects.append("item")

    def _record(name: str) -> Any:
        def _inner(*args: object, **kwargs: object) -> None:
            del args, kwargs
            side_effects.append(name)

        return _inner

    monkeypatch.setattr(routes_events, "_evaluate_input_policy", _policy)
    monkeypatch.setattr(routes_events, "_persist_policy_deny_sentinel", _persist)
    monkeypatch.setattr(routes_events, "_publish_status", _record("status"))
    monkeypatch.setattr(routes_events, "_publish_policy_deny", _record("policy_publish"))
    monkeypatch.setattr(routes_events, "_publish_input_deny_terminal", _record("terminal"))

    response = await client.post(
        f"/v1/sessions/{session_id}/events",
        json={
            "type": "message",
            "data": {"role": "user", "content": [{"type": "input_text", "text": "go"}]},
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert side_effects == []
    assert SqlAlchemyConversationStore(db_uri).list_items(session_id).data == []
