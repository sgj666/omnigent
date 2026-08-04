"""Tests for Sessions API CRUD endpoints (list, get, delete, patch).

Exercises the core session management routes through the ``client``
fixture. Since the lifespan event (which seeds agents) does not run
in test fixtures, we seed a test agent and conversation directly via
the stores.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from omnigent.db.utils import generate_agent_id
from omnigent.entities import Agent, AgentBundleSnapshot, Conversation, PagedList
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.routes import sessions as sessions_module
from omnigent.server.routes._session_create_validation import pin_session_agent_bundle
from omnigent.server.routes._sessions import orchestration as session_orchestration
from omnigent.server.routes.sessions import create_sessions_router
from omnigent.server.routes.sessions import routes_core as sessions_core
from omnigent.server.schemas import (
    SessionAgentBundleExpectation,
    SessionCreateMetadata,
    SessionCreateRequest,
)
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import (
    SqlAlchemyConversationStore,
)


def _snapshot_kwargs(agent: Agent) -> dict[str, object]:
    snapshot = AgentBundleSnapshot.from_agent(agent)
    return {
        "agent_bundle_version": snapshot.bundle_version,
        "agent_bundle_digest": snapshot.bundle_digest,
        "agent_bundle_location": snapshot.bundle_location,
    }


class _FirstReadConversationStore:
    """Minimal store that records list/watch auxiliary reads."""

    def __init__(self, conversations: list[Conversation], calls: list[str]) -> None:
        self._conversations = conversations
        self._by_id = {conversation.id: conversation for conversation in conversations}
        self._calls = calls

    def list_conversations(self, **kwargs: object) -> PagedList[Conversation]:
        del kwargs
        return PagedList(
            data=self._conversations,
            first_id=self._conversations[0].id,
            last_id=self._conversations[-1].id,
            has_more=False,
        )

    def get_conversations(self, conversation_ids: list[str]) -> dict[str, Conversation]:
        return {
            conversation_id: self._by_id[conversation_id]
            for conversation_id in conversation_ids
            if conversation_id in self._by_id
        }

    def list_child_conversation_ids_by_parent(
        self, conversation_ids: list[str]
    ) -> dict[str, list[str]]:
        self._calls.append("children")
        return {conversation_id: [] for conversation_id in conversation_ids}


class _FirstReadAgentStore:
    """Minimal Agent store that records bulk name reads."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def get_names(self, agent_ids: list[str]) -> dict[str, str]:
        self._calls.append("agent_names")
        return dict.fromkeys(agent_ids, "agent")


class _FirstReadCommentStore:
    """Minimal comment store that records fingerprint reads."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def get_comments_fingerprints(self, conversation_ids: list[str]) -> dict[str, object]:
        del conversation_ids
        self._calls.append("comments")
        return {}


def _first_read_app(
    conversations: list[Conversation],
    calls: list[str],
    *,
    liveness_lookup: Any | None = None,
) -> FastAPI:
    """Build a list/watch app whose auxiliary reads are observable."""
    app = FastAPI()

    @app.exception_handler(OmnigentError)
    async def _handle_omnigent_error(
        request: Request,
        exc: OmnigentError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(
        create_sessions_router(
            conversation_store=_FirstReadConversationStore(conversations, calls),  # type: ignore[arg-type]
            agent_store=_FirstReadAgentStore(calls),  # type: ignore[arg-type]
            comment_store=_FirstReadCommentStore(calls),  # type: ignore[arg-type]
            liveness_lookup=liveness_lookup,
        ),
        prefix="/v1",
    )
    return app


def test_session_projections_expose_bundle_identity_but_not_location() -> None:
    digest = "a" * 64
    conversation = Conversation(
        id="conv_projection",
        created_at=10,
        updated_at=11,
        root_conversation_id="conv_projection",
        agent_id="agent_projection",
        agent_bundle_version=5,
        agent_bundle_digest=digest,
        agent_bundle_location=f"agent_projection/{digest}",
    )

    snapshot = sessions_module._build_session_response(  # type: ignore[attr-defined]
        conversation,
        [],
        "idle",
    ).model_dump()
    list_item = sessions_module._build_session_list_item(  # type: ignore[attr-defined]
        conversation,
        agent_names_by_id={"agent_projection": "projection"},
        grants=[],
        user_id=None,
        user_is_admin=False,
        permissions_enabled=False,
        pending_count=0,
        child_session_ids=[],
        comments_fingerprint=None,
    ).model_dump()

    for projection in (snapshot, list_item):
        assert projection["agent_bundle_version"] == 5
        assert projection["agent_bundle_digest"] == digest
        assert "agent_bundle_location" not in projection


def test_child_validation_uses_parent_pinned_bundle() -> None:
    pinned_digest = "a" * 64
    current_digest = "b" * 64
    agent = Agent(
        id="agent_child",
        created_at=1,
        name="child",
        version=9,
        bundle_location=f"agent_child/{current_digest}",
    )
    parent = Conversation(
        id="conv_parent",
        created_at=2,
        updated_at=2,
        root_conversation_id="conv_parent",
        agent_id="agent_parent",
        agent_bundle_version=3,
        agent_bundle_digest=pinned_digest,
        agent_bundle_location=f"agent_parent/{pinned_digest}",
    )

    pinned_agent, snapshot = pin_session_agent_bundle(agent, parent)

    assert pinned_agent.version == 3
    assert pinned_agent.bundle_location == f"agent_parent/{pinned_digest}"
    assert snapshot.bundle_version == 3
    assert snapshot.bundle_digest == pinned_digest


def test_child_validation_rejects_legacy_parent_snapshot() -> None:
    digest = "a" * 64
    agent = Agent(
        id="agent_child",
        created_at=1,
        name="child",
        bundle_location=f"agent_child/{digest}",
    )
    legacy_parent = Conversation(
        id="conv_legacy_parent",
        created_at=2,
        updated_at=2,
        root_conversation_id="conv_legacy_parent",
        agent_id="agent_parent",
    )

    with pytest.raises(OmnigentError) as exc_info:
        pin_session_agent_bundle(agent, legacy_parent)

    assert exc_info.value.code == ErrorCode.CONFLICT


@pytest.mark.parametrize(
    ("version", "digest", "location"),
    [
        (1, None, None),
        (1, "a" * 64, f"{'1' * 32}/{'b' * 64}"),
    ],
    ids=["partial", "invalid-complete"],
)
async def test_json_child_validates_parent_before_target_agent_lookup(
    monkeypatch: pytest.MonkeyPatch,
    version: int | None,
    digest: str | None,
    location: str | None,
) -> None:
    """A corrupt JSON Parent blocks target-Agent I/O before mutation."""
    agent_id = "1" * 32
    parent = Conversation(
        id="2" * 32,
        created_at=1,
        updated_at=1,
        root_conversation_id="2" * 32,
        agent_id=agent_id,
        agent_bundle_version=version,
        agent_bundle_digest=digest,
        agent_bundle_location=location,
    )
    agent_calls: list[str] = []

    class _ConversationStore:
        @staticmethod
        def get_conversation(conversation_id: str) -> Conversation | None:
            return parent if conversation_id == parent.id else None

    async def _record_validate_session_agent(**kwargs: object) -> Agent:
        agent_calls.append(str(kwargs["agent_id"]))
        return Agent(
            id=agent_id,
            created_at=1,
            name="target",
            bundle_location=f"{agent_id}/{'c' * 64}",
        )

    monkeypatch.setattr(
        session_orchestration,
        "validate_session_agent",
        _record_validate_session_agent,
    )

    with pytest.raises(OmnigentError) as exc_info:
        await session_orchestration._create_session_from_existing_agent(
            _ConversationStore(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            None,
            SessionCreateRequest(agent_id=agent_id, parent_session_id=parent.id),
            object(),  # type: ignore[arg-type]
        )

    assert exc_info.value.code == ErrorCode.CONFLICT
    assert agent_calls == []


async def test_json_create_rejects_changed_expected_bundle_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Run-pinned Root expectation is checked before any Session row exists."""
    agent_id = "1" * 32
    actual_digest = "a" * 64
    agent = Agent(
        id=agent_id,
        created_at=1,
        name="coordinator",
        version=4,
        bundle_location=f"{agent_id}/{actual_digest}",
    )
    create_calls: list[dict[str, object]] = []

    class _ConversationStore:
        @staticmethod
        def create_conversation(**kwargs: object) -> None:
            create_calls.append(kwargs)
            raise AssertionError("mismatched snapshot must not create a conversation")

    async def _validate_session_agent(**_kwargs: object) -> Agent:
        return agent

    monkeypatch.setattr(
        session_orchestration,
        "validate_session_agent",
        _validate_session_agent,
    )

    with pytest.raises(OmnigentError) as exc_info:
        await session_orchestration._create_session_from_existing_agent(
            _ConversationStore(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            None,
            SessionCreateRequest(
                agent_id=agent_id,
                expected_agent_bundle=SessionAgentBundleExpectation(
                    version=4,
                    digest="b" * 64,
                    location=f"{agent_id}/{'b' * 64}",
                ),
            ),
            object(),  # type: ignore[arg-type]
        )

    assert exc_info.value.code == ErrorCode.CONFLICT
    assert create_calls == []


def test_persist_stored_session_bundle_cleans_snapshot_value_error(
    tmp_path: Any,
) -> None:
    """A Parent snapshot race cannot orphan an already-uploaded bundle."""
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    location = f"agent_child/{'a' * 64}"
    artifact_store.put(location, b"bundle")

    class _ConversationStore:
        @staticmethod
        def create_session_with_agent(**kwargs: object) -> None:
            del kwargs
            raise ValueError("parent conversation has no valid agent Bundle snapshot")

    with pytest.raises(OmnigentError) as exc_info:
        sessions_module._persist_stored_session_bundle(  # type: ignore[attr-defined]
            _ConversationStore(),  # type: ignore[arg-type]
            artifact_store,
            SessionCreateMetadata(parent_session_id="conv_parent"),
            agent_id="agent_child",
            agent_name="child",
            agent_bundle_location=location,
            agent_description=None,
        )

    assert exc_info.value.code == ErrorCode.CONFLICT
    with pytest.raises(KeyError):
        artifact_store.get(location)


@pytest_asyncio.fixture()
async def session_id(db_uri: str) -> str:
    """Seed a test agent and conversation, return the session ID."""
    agent_store = SqlAlchemyAgentStore(db_uri)
    conv_store = SqlAlchemyConversationStore(db_uri)
    agent_id = generate_agent_id()
    agent = agent_store.create(
        agent_id,
        name="test-agent",
        bundle_location=f"{agent_id}/{'a' * 64}",
    )
    conv = conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))
    return conv.id


# ── GET /v1/sessions (list) ─────────────────────────────────────────


async def test_list_sessions_empty(client: httpx.AsyncClient) -> None:
    """Empty database returns an empty list."""
    resp = await client.get("/v1/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["has_more"] is False


async def test_list_sessions_after_create(
    client: httpx.AsyncClient,
    session_id: str,
) -> None:
    """A created session appears in the list."""
    resp = await client.get("/v1/sessions")
    assert resp.status_code == 200
    body = resp.json()
    ids = [s["id"] for s in body["data"]]
    assert session_id in ids


async def test_list_sessions_pagination(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Pagination with limit returns at most N sessions."""
    agent_store = SqlAlchemyAgentStore(db_uri)
    conv_store = SqlAlchemyConversationStore(db_uri)
    agent_id = generate_agent_id()
    agent = agent_store.create(
        agent_id,
        name="pag-agent",
        bundle_location=f"{agent_id}/{'a' * 64}",
    )
    conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))
    conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))

    resp = await client.get("/v1/sessions?limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1


def test_list_sessions_validates_full_batch_before_auxiliary_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt later row blocks every list projection helper."""
    agent_id = "1" * 32
    digest = "2" * 64
    valid = Conversation(
        id="3" * 32,
        created_at=1,
        updated_at=1,
        root_conversation_id="3" * 32,
        agent_id=agent_id,
        agent_bundle_version=1,
        agent_bundle_digest=digest,
        agent_bundle_location=f"{agent_id}/{digest}",
    )
    corrupt = Conversation(
        id="4" * 32,
        created_at=2,
        updated_at=2,
        root_conversation_id="4" * 32,
        agent_id=agent_id,
        agent_bundle_version=1,
    )
    calls: list[str] = []
    original_builder = sessions_core._build_session_list_item

    def _record_builder(*args: object, **kwargs: object) -> object:
        calls.append("status")
        return original_builder(*args, **kwargs)  # type: ignore[arg-type]

    def _record_pending(conversation_ids: list[str]) -> dict[str, int]:
        del conversation_ids
        calls.append("pending")
        return {}

    monkeypatch.setattr(sessions_core, "_build_session_list_item", _record_builder)
    monkeypatch.setattr(sessions_core.pending_elicitations, "counts_for", _record_pending)

    response = TestClient(_first_read_app([valid, corrupt], calls)).get("/v1/sessions")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert calls == []


def test_watch_validates_full_batch_before_auxiliary_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt later watched row closes before projection or liveness."""
    agent_id = "5" * 32
    digest = "6" * 64
    valid = Conversation(
        id="7" * 32,
        created_at=1,
        updated_at=1,
        root_conversation_id="7" * 32,
        agent_id=agent_id,
        agent_bundle_version=1,
        agent_bundle_digest=digest,
        agent_bundle_location=f"{agent_id}/{digest}",
    )
    corrupt = Conversation(
        id="8" * 32,
        created_at=2,
        updated_at=2,
        root_conversation_id="8" * 32,
        agent_id=agent_id,
        agent_bundle_version=1,
        agent_bundle_digest="9" * 64,
        agent_bundle_location=f"{agent_id}/{'a' * 64}",
    )
    calls: list[str] = []
    original_builder = sessions_core._build_session_list_item

    def _record_builder(*args: object, **kwargs: object) -> object:
        calls.append("status")
        return original_builder(*args, **kwargs)  # type: ignore[arg-type]

    def _record_pending(conversation_ids: list[str]) -> dict[str, int]:
        del conversation_ids
        calls.append("pending")
        return {}

    def _record_liveness(conversation_ids: list[str]) -> dict[str, object]:
        del conversation_ids
        calls.append("liveness")
        return {}

    monkeypatch.setattr(sessions_core, "_build_session_list_item", _record_builder)
    monkeypatch.setattr(sessions_core.pending_elicitations, "counts_for", _record_pending)
    app = _first_read_app([valid, corrupt], calls, liveness_lookup=_record_liveness)

    with TestClient(app).websocket_connect("/v1/sessions/updates") as websocket:
        websocket.send_text(
            '{"type":"watch","session_ids":["' + valid.id + '","' + corrupt.id + '"]}'
        )
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_text()

    assert calls == []


# ── GET /v1/sessions/{id} (get snapshot) ────────────────────────────


async def test_get_session(
    client: httpx.AsyncClient,
    session_id: str,
) -> None:
    """Get a session by ID returns its snapshot."""
    resp = await client.get(f"/v1/sessions/{session_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == session_id


async def test_get_session_not_found(client: httpx.AsyncClient) -> None:
    """Getting a nonexistent session returns 404."""
    resp = await client.get("/v1/sessions/4fe12335002377c209e501c3fe3bcffc")
    assert resp.status_code == 404


# ── DELETE /v1/sessions/{id} ────────────────────────────────────────


async def test_delete_session(
    client: httpx.AsyncClient,
    session_id: str,
) -> None:
    """Deleting a session returns 200 with deleted: true."""
    resp = await client.delete(f"/v1/sessions/{session_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True


async def test_delete_session_not_found(client: httpx.AsyncClient) -> None:
    """Deleting a nonexistent session returns 404."""
    resp = await client.delete("/v1/sessions/4fe12335002377c209e501c3fe3bcffc")
    assert resp.status_code == 404


async def test_delete_running_session_attempts_stop(
    client: httpx.AsyncClient,
    session_id: str,
) -> None:
    """Deleting a running session calls ``_stop_session_via_runner``."""
    mock_stop = AsyncMock(return_value=True)
    sessions_module._session_status_cache[session_id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.delete(f"/v1/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        mock_stop.assert_awaited_once()
    finally:
        sessions_module._session_status_cache.pop(session_id, None)


async def test_delete_idle_parent_stops_running_child(
    client: httpx.AsyncClient,
    session_id: str,
    db_uri: str,
) -> None:
    """Deleting an idle parent with a running child stops the child.

    Regression test: ``_best_effort_stop`` previously used the child
    rollup only to decide whether to act, then always issued the stop
    against the parent's own session id. A parent that has already gone
    idle while its sub-agent child keeps running would get a no-op stop,
    then the recursive subtree delete would remove the child's row while
    its runner process kept running, orphaning it.
    """
    conv_store = SqlAlchemyConversationStore(db_uri)
    child = conv_store.create_conversation(
        kind="sub_agent",
        title="researcher:auth",
        parent_conversation_id=session_id,
    )

    mock_stop = AsyncMock(return_value=True)
    sessions_module._session_status_cache[child.id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.delete(f"/v1/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        # The child must be the one stopped, not the (idle) parent.
        mock_stop.assert_awaited_once()
        assert mock_stop.await_args is not None
        assert mock_stop.await_args.args[0] == child.id
    finally:
        sessions_module._session_status_cache.pop(child.id, None)


async def test_delete_idle_parent_stops_running_grandchild(
    client: httpx.AsyncClient,
    session_id: str,
    db_uri: str,
) -> None:
    """Deleting an idle parent stops a running grandchild too.

    Regression test: ``_best_effort_stop`` used to walk only direct
    children, one level down. A sub-agent that itself spawns a sub-agent
    (parent -> child -> grandchild) with the child now idle but the
    grandchild still running was invisible to that one-level check, so
    the grandchild kept running unstopped -- the same bug as the direct-
    child case, just one generation deeper. ``delete_conversation``'s
    recursive subtree delete has no such depth limit, so the stop logic
    must match it.
    """
    conv_store = SqlAlchemyConversationStore(db_uri)
    child = conv_store.create_conversation(
        kind="sub_agent",
        title="researcher:auth",
        parent_conversation_id=session_id,
    )
    grandchild = conv_store.create_conversation(
        kind="sub_agent",
        title="researcher:citations",
        parent_conversation_id=child.id,
    )

    mock_stop = AsyncMock(return_value=True)
    sessions_module._session_status_cache[grandchild.id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.delete(f"/v1/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        # The grandchild must be the one stopped, not the idle parent/child.
        mock_stop.assert_awaited_once()
        assert mock_stop.await_args is not None
        assert mock_stop.await_args.args[0] == grandchild.id
    finally:
        sessions_module._session_status_cache.pop(grandchild.id, None)


async def test_delete_proceeds_when_stop_fails(
    client: httpx.AsyncClient,
    session_id: str,
) -> None:
    """Delete succeeds even when the runner stop raises."""
    mock_stop = AsyncMock(side_effect=ConnectionError("runner gone"))
    sessions_module._session_status_cache[session_id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.delete(f"/v1/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
    finally:
        sessions_module._session_status_cache.pop(session_id, None)


# ── PATCH /v1/sessions/{id} ─────────────────────────────────────────


async def test_patch_session_title(
    client: httpx.AsyncClient,
    session_id: str,
) -> None:
    """Patching a session's title returns the updated session."""
    resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"title": "New Title"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200


async def test_patch_session_not_found(client: httpx.AsyncClient) -> None:
    """Patching a nonexistent session returns 404."""
    resp = await client.patch(
        "/v1/sessions/4fe12335002377c209e501c3fe3bcffc",
        json={"title": "New Title"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 404


# ── GET /v1/sessions/projects ────────────────────────────────────────


async def test_list_projects_empty(client: httpx.AsyncClient) -> None:
    """No project labels anywhere → empty project list."""
    resp = await client.get("/v1/sessions/projects")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_projects_returns_names_sorted(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Projects surface as a sorted list of names."""
    conv_store = SqlAlchemyConversationStore(db_uri)
    a = conv_store.create_conversation()
    b = conv_store.create_conversation()
    conv_store.set_labels(a.id, {"omni_project": "Sprint 42"})
    conv_store.set_labels(b.id, {"omni_project": "Customer X"})

    resp = await client.get("/v1/sessions/projects")
    assert resp.status_code == 200
    # Label-only projects (no first-class row) list with id=None, sorted by name.
    assert resp.json() == [
        {"id": None, "name": "Customer X"},
        {"id": None, "name": "Sprint 42"},
    ]


# ── GET /v1/sessions?project= (filter) ───────────────────────────────


async def test_list_sessions_filtered_by_project(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """``?project=X`` returns only sessions in that project."""
    agent_store = SqlAlchemyAgentStore(db_uri)
    conv_store = SqlAlchemyConversationStore(db_uri)
    # GET /v1/sessions filters has_agent_id=True, so bind the conversations to
    # a seeded agent — otherwise the list comes back empty.
    agent_id = generate_agent_id()
    agent = agent_store.create(
        agent_id,
        name="project-agent",
        bundle_location=f"{agent_id}/{'a' * 64}",
    )
    filed = conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))
    conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))  # unfiled
    conv_store.set_labels(filed.id, {"omni_project": "X"})

    resp = await client.get("/v1/sessions?project=X")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()["data"]]
    assert ids == [filed.id]


async def test_list_sessions_empty_project_returns_unfiled(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """``?project=`` (empty) returns only sessions with no project label."""
    agent_store = SqlAlchemyAgentStore(db_uri)
    conv_store = SqlAlchemyConversationStore(db_uri)
    agent_id = generate_agent_id()
    agent = agent_store.create(
        agent_id,
        name="project-agent",
        bundle_location=f"{agent_id}/{'a' * 64}",
    )
    filed = conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))
    unfiled = conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))
    conv_store.set_labels(filed.id, {"omni_project": "X"})

    resp = await client.get("/v1/sessions?project=")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()["data"]]
    assert unfiled.id in ids
    assert filed.id not in ids


# ── PATCH /v1/sessions/{id} project label ────────────────────────────


async def test_patch_session_sets_project_label(
    client: httpx.AsyncClient,
    session_id: str,
    db_uri: str,
) -> None:
    """PATCH with ``labels: {project: X}`` upserts the project label."""
    resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"labels": {"omni_project": "Sprint 42"}},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    conv_store = SqlAlchemyConversationStore(db_uri)
    conv = conv_store.get_conversation(session_id)
    assert conv is not None
    assert conv.labels.get("omni_project") == "Sprint 42"


async def test_patch_session_empty_project_removes_label(
    client: httpx.AsyncClient,
    session_id: str,
    db_uri: str,
) -> None:
    """PATCH with ``labels: {project: ""}`` removes the project label rather
    than persisting an empty value — so the session returns to Unfiled."""
    conv_store = SqlAlchemyConversationStore(db_uri)
    conv_store.set_labels(session_id, {"omni_project": "Sprint 42"})

    resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"labels": {"omni_project": ""}},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    conv = conv_store.get_conversation(session_id)
    assert conv is not None
    assert "omni_project" not in conv.labels


# ── Pinned session label (omnigent.pinned) ───────────────────────────


async def test_patch_session_pins_and_unpins(
    client: httpx.AsyncClient,
    session_id: str,
    db_uri: str,
) -> None:
    """PATCH with the canonical ``labels: {"omnigent.pinned": <pin-time>}`` pins
    the session for the CALLER: the server rewrites it to the per-user key
    ``omnigent.pinned.<user>`` in storage (so it doesn't pin for others), and an
    empty value deletes that per-user key (unpin)."""
    from omnigent.stores.conversation_store import pinned_label_key

    conv_store = SqlAlchemyConversationStore(db_uri)
    # No auth header on this client ⇒ the single-user ``local`` identity.
    user_key = pinned_label_key(None)

    resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"labels": {"omnigent.pinned": "1721760000000"}},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    conv = conv_store.get_conversation(session_id)
    assert conv is not None
    # Stored under the per-user key, NOT the bare canonical key.
    assert conv.labels.get(user_key) == "1721760000000"
    assert "omnigent.pinned" not in conv.labels
    # …but the response collapses it back to the canonical key for the caller.
    assert resp.json()["labels"].get("omnigent.pinned") == "1721760000000"

    # Unpin: empty string clears the per-user key.
    resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"labels": {"omnigent.pinned": ""}},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    conv = conv_store.get_conversation(session_id)
    assert conv is not None
    assert user_key not in conv.labels


async def test_patch_rejects_client_supplied_per_user_pin_key(
    client: httpx.AsyncClient,
    session_id: str,
    db_uri: str,
) -> None:
    """A client may only write the bare canonical ``omnigent.pinned`` key. A
    suffixed ``omnigent.pinned.<user>`` is server-derived — accepting one would
    let a caller pin/unpin a shared session for another user. It must be
    rejected, and nothing persisted."""
    conv_store = SqlAlchemyConversationStore(db_uri)

    for value in ("1721760000000", ""):
        resp = await client.patch(
            f"/v1/sessions/{session_id}",
            json={"labels": {"omnigent.pinned.bob@example.com": value}},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
    conv = conv_store.get_conversation(session_id)
    assert conv is not None
    assert "omnigent.pinned.bob@example.com" not in conv.labels


async def test_list_sessions_pinned_filter(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """``?pinned=true`` returns only sessions the CALLER pinned — matched by
    their per-user key. Another user's pin on a session does not surface."""
    from omnigent.stores.conversation_store import pinned_label_key

    agent_store = SqlAlchemyAgentStore(db_uri)
    conv_store = SqlAlchemyConversationStore(db_uri)
    agent_id = generate_agent_id()
    agent = agent_store.create(
        agent_id,
        name="pin-agent",
        bundle_location=f"{agent_id}/{'a' * 64}",
    )
    pinned = conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))
    plain = conv_store.create_conversation(agent_id=agent_id, **_snapshot_kwargs(agent))
    other_user_pin = conv_store.create_conversation(
        agent_id=agent_id,
        **_snapshot_kwargs(agent),
    )
    # This client is unauthenticated ⇒ the ``local`` identity. Pin one session
    # under the caller's key and one under a different user's key.
    conv_store.set_labels(pinned.id, {pinned_label_key(None): "1721760000000"})
    conv_store.set_labels(other_user_pin.id, {pinned_label_key("someone-else"): "1721760000000"})

    resp = await client.get("/v1/sessions?pinned=true")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()["data"]]
    assert pinned.id in ids
    assert plain.id not in ids
    # A pin belonging to another user must not appear for the caller.
    assert other_user_pin.id not in ids
