"""CRUD and ownership tests for product Tasks (``/v1/work-items``)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import update

from omnigent.db.db_models import SqlWorkItem, current_workspace_id
from omnigent.db.utils import get_or_create_engine
from omnigent.entities import AgentBundleSnapshot
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runs.session_gateway import ASGISessionGateway
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.inbox_item_store.sqlalchemy_store import SqlAlchemyInboxItemStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from omnigent.stores.work_item_run_store.sqlalchemy_store import SqlAlchemyWorkItemRunStore
from omnigent.stores.work_item_store.sqlalchemy_store import SqlAlchemyWorkItemStore


def _build_app(
    db_uri: str,
    tmp_path: Path,
    *,
    auth_provider: UnifiedAuthProvider | None = None,
) -> FastAPI:
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    return create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=SqlAlchemyConversationStore(db_uri),
        artifact_store=artifacts,
        agent_cache=AgentCache(artifact_store=artifacts, cache_dir=tmp_path / "cache"),
        project_store=SqlAlchemyProjectStore(db_uri),
        work_item_store=SqlAlchemyWorkItemStore(db_uri),
        work_item_run_store=SqlAlchemyWorkItemRunStore(db_uri),
        inbox_item_store=SqlAlchemyInboxItemStore(db_uri),
        auth_provider=auth_provider,
    )


@pytest_asyncio.fixture()
async def work_item_client(
    runtime_init: None,
    db_uri: str,
    tmp_path: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_build_app(db_uri, tmp_path))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_create_list_get_and_update_work_item(work_item_client: httpx.AsyncClient) -> None:
    created_response = await work_item_client.post(
        "/v1/work-items",
        json={"title": "Ship Task board", "description": "Phase 2", "priority": "high"},
    )
    assert created_response.status_code == 200
    created = created_response.json()
    assert (
        created
        | {
            "object": "work_item",
            "title": "Ship Task board",
            "state": "backlog",
            "priority": "high",
            "version": 1,
            "creator_kind": "user",
            "created_by_agent_id": None,
        }
        == created
    )

    listed = (await work_item_client.get("/v1/work-items")).json()
    assert [item["id"] for item in listed["data"]] == [created["id"]]
    assert (await work_item_client.get(f"/v1/work-items/{created['id']}")).json() == created

    updated_response = await work_item_client.patch(
        f"/v1/work-items/{created['id']}",
        json={"state": "in_progress", "expected_version": 1},
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["state"] == "in_progress"
    assert updated["version"] == 2
    assert updated["updated_at"] is not None


async def test_agent_creator_provenance_and_outcome_states(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    agent_id = "a" * 32
    creator = SqlAlchemyAgentStore(db_uri).create(
        agent_id,
        name="task-creator",
        bundle_location=f"{agent_id}/{'b' * 64}",
    )
    snapshot = AgentBundleSnapshot.from_agent(creator)
    conversation = SqlAlchemyConversationStore(db_uri).create_conversation(
        agent_id=agent_id,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    created = await work_item_client.post(
        "/v1/work-items",
        headers={
            "X-Orvia-Creator-Agent-Id": agent_id,
            "X-Orvia-Creator-Session-Id": conversation.id,
        },
        json={"title": "Agent-created task"},
    )
    assert created.status_code == 200
    task = created.json()
    assert task["creator_kind"] == "agent"
    assert task["created_by_agent_id"] == agent_id
    assert task["assignee_agent_id"] == agent_id

    blocked = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"state": "blocked", "expected_version": task["version"]},
    )
    assert blocked.status_code == 200
    failed = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"state": "failed", "expected_version": blocked.json()["version"]},
    )
    assert failed.status_code == 200
    assert failed.json()["state"] == "failed"


async def test_coordinator_can_assign_an_agent_created_task(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    agent_store = SqlAlchemyAgentStore(db_uri)
    coordinator_id = "c" * 32
    worker_id = "d" * 32
    coordinator = agent_store.create(
        coordinator_id,
        name="task-coordinator",
        bundle_location=f"{coordinator_id}/{'c' * 64}",
    )
    agent_store.create(
        worker_id,
        name="task-worker",
        bundle_location=f"{worker_id}/{'d' * 64}",
    )
    snapshot = AgentBundleSnapshot.from_agent(coordinator)
    conversation = SqlAlchemyConversationStore(db_uri).create_conversation(
        agent_id=coordinator_id,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )

    response = await work_item_client.post(
        "/v1/work-items",
        headers={
            "X-Orvia-Creator-Agent-Id": coordinator_id,
            "X-Orvia-Creator-Session-Id": conversation.id,
        },
        json={"title": "Delegated task", "assignee_agent_id": worker_id},
    )

    assert response.status_code == 200
    assert response.json()["created_by_agent_id"] == coordinator_id
    assert response.json()["assignee_agent_id"] == worker_id


async def test_sub_agent_cannot_create_or_assign_a_task(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    agent_id = "e" * 32
    creator = SqlAlchemyAgentStore(db_uri).create(
        agent_id,
        name="multi-agent-coordinator",
        bundle_location=f"{agent_id}/{'e' * 64}",
    )
    snapshot = AgentBundleSnapshot.from_agent(creator)
    conversation_store = SqlAlchemyConversationStore(db_uri)
    coordinator = conversation_store.create_conversation(
        agent_id=agent_id,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    worker = conversation_store.create_conversation(
        kind="sub_agent",
        title="worker:implementation",
        parent_conversation_id=coordinator.id,
        agent_id=agent_id,
        sub_agent_name="worker",
    )

    response = await work_item_client.post(
        "/v1/work-items",
        headers={
            "X-Orvia-Creator-Agent-Id": agent_id,
            "X-Orvia-Creator-Session-Id": worker.id,
        },
        json={"title": "Worker-created task"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.FORBIDDEN


async def test_task_run_waiting_and_failure_project_to_board_state(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    from omnigent.server import session_live_state

    agent_id = "b" * 32
    SqlAlchemyAgentStore(db_uri).create(
        agent_id,
        name="task-runner",
        bundle_location="test:///bundle",
    )
    task = (
        await work_item_client.post(
            "/v1/work-items",
            json={"title": "State projection", "assignee_agent_id": agent_id},
        )
    ).json()
    run_store = SqlAlchemyWorkItemRunStore(db_uri)
    run = run_store.create(
        "c" * 32,
        work_item_id=task["id"],
        owner_user_id=None,
        agent_id=agent_id,
        runtime_id="runtime-local",
        workspace="/tmp/orvia-task",
        trigger="manual",
        retry_of_run_id=None,
    )
    run_store.bind_session(run.id, owner_user_id=None, session_id="d" * 32)

    session_live_state.persist_work_item_run_status("d" * 32, "waiting")
    for _ in range(30):
        current = (await work_item_client.get(f"/v1/work-items/{task['id']}")).json()
        if current["state"] == "blocked":
            break
        await asyncio.sleep(0.01)
    assert current["state"] == "blocked"

    session_live_state.persist_work_item_run_status(
        "d" * 32,
        "failed",
        error_code="runner_unavailable",
        error_message="offline",
    )
    for _ in range(30):
        current = (await work_item_client.get(f"/v1/work-items/{task['id']}")).json()
        if current["state"] == "failed":
            break
        await asyncio.sleep(0.01)
    assert current["state"] == "failed"


async def test_update_rejects_stale_version(work_item_client: httpx.AsyncClient) -> None:
    task = (await work_item_client.post("/v1/work-items", json={"title": "Conflict"})).json()
    first = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"state": "todo", "expected_version": 1},
    )
    assert first.status_code == 200

    stale = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"state": "done", "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"


async def test_task_completion_creates_persistent_readable_inbox_item(
    work_item_client: httpx.AsyncClient,
) -> None:
    task = (await work_item_client.post("/v1/work-items", json={"title": "Finish me"})).json()
    completed = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"state": "done", "expected_version": 1},
    )
    assert completed.status_code == 200

    data: dict = {}
    for _ in range(20):
        data = (await work_item_client.get("/v1/inbox-items")).json()
        if data.get("data"):
            break
        await asyncio.sleep(0.01)
    assert data["unread_count"] == 1
    assert (
        data["data"][0]
        | {
            "kind": "task_completed",
            "work_item_id": task["id"],
            "message": "Finish me",
            "target_url": f"/tasks/{task['id']}",
            "read_at": None,
        }
        == data["data"][0]
    )

    item_id = data["data"][0]["id"]
    marked = await work_item_client.patch(f"/v1/inbox-items/{item_id}", json={"read": True})
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert (await work_item_client.get("/v1/inbox-items")).json()["unread_count"] == 0


async def test_repeated_task_completion_event_is_deduplicated(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    task = (await work_item_client.post("/v1/work-items", json={"title": "Once"})).json()
    completed = (
        await work_item_client.patch(
            f"/v1/work-items/{task['id']}",
            json={"state": "done", "expected_version": 1},
        )
    ).json()
    from omnigent.server import session_live_state

    persisted = SqlAlchemyWorkItemStore(db_uri).get(completed["id"], owner_user_id=None)
    assert persisted is not None
    session_live_state.persist_work_item_completed(
        type(
            "Item",
            (),
            {
                "id": completed["id"],
                "owner_user_id": None,
                "title": completed["title"],
                "version": completed["version"],
                "completion_id": persisted.completion_id,
            },
        )()
    )
    await asyncio.sleep(0.05)
    for _ in range(20):
        rows = (await work_item_client.get("/v1/inbox-items")).json()["data"]
        if rows:
            break
        await asyncio.sleep(0.01)
    assert len(rows) == 1


async def test_done_task_edit_does_not_create_a_second_completion_notification(
    work_item_client: httpx.AsyncClient,
) -> None:
    task = (await work_item_client.post("/v1/work-items", json={"title": "Stable"})).json()
    completed = (
        await work_item_client.patch(
            f"/v1/work-items/{task['id']}",
            json={"state": "done", "expected_version": 1},
        )
    ).json()

    for _ in range(20):
        rows = (await work_item_client.get("/v1/inbox-items")).json()["data"]
        if rows:
            break
        await asyncio.sleep(0.01)
    assert len(rows) == 1

    edited = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"priority": "high", "expected_version": completed["version"]},
    )
    assert edited.status_code == 200

    first = (await work_item_client.get("/v1/inbox-items")).json()
    second = (await work_item_client.get("/v1/inbox-items")).json()
    assert [row["id"] for row in first["data"]] == [row["id"] for row in rows]
    assert [row["id"] for row in second["data"]] == [row["id"] for row in rows]


async def test_setting_an_already_done_task_to_done_reuses_the_completion_event(
    work_item_client: httpx.AsyncClient,
) -> None:
    task = (await work_item_client.post("/v1/work-items", json={"title": "Still done"})).json()
    completed = (
        await work_item_client.patch(
            f"/v1/work-items/{task['id']}",
            json={"state": "done", "expected_version": 1},
        )
    ).json()
    repeated = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"state": "done", "expected_version": completed["version"]},
    )
    assert repeated.status_code == 200

    for _ in range(20):
        rows = (await work_item_client.get("/v1/inbox-items")).json()["data"]
        if rows:
            break
        await asyncio.sleep(0.01)
    assert [(row["kind"], row["message"]) for row in rows] == [("task_completed", "Still done")]


async def test_inbox_read_repair_recovers_a_missing_task_completion_projection(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch,
) -> None:
    from omnigent.server import session_live_state

    monkeypatch.setattr(session_live_state, "persist_work_item_completed", lambda _item: None)
    task = (await work_item_client.post("/v1/work-items", json={"title": "Repair me"})).json()
    completed = await work_item_client.patch(
        f"/v1/work-items/{task['id']}",
        json={"state": "done", "expected_version": 1},
    )
    assert completed.status_code == 200
    assert SqlAlchemyInboxItemStore(db_uri).list(owner_user_id=None) == []

    first = (await work_item_client.get("/v1/inbox-items")).json()
    second = (await work_item_client.get("/v1/inbox-items")).json()
    assert [(row["kind"], row["message"]) for row in first["data"]] == [
        ("task_completed", "Repair me")
    ]
    assert [row["id"] for row in second["data"]] == [row["id"] for row in first["data"]]


async def test_inbox_read_repair_recognizes_a_legacy_completion_projection(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch,
) -> None:
    from omnigent.server import session_live_state

    agent_id = "c" * 32
    SqlAlchemyAgentStore(db_uri).create(
        agent_id,
        name="legacy-repair-runner",
        bundle_location="test:///bundle",
    )

    async def create_session(_self, _command):
        return "b" * 32

    async def send_input(_self, _session_id, _event, _actor_id):
        return None

    monkeypatch.setattr(ASGISessionGateway, "create_task_session", create_session)
    monkeypatch.setattr(ASGISessionGateway, "send_input", send_input)
    monkeypatch.setattr(session_live_state, "persist_work_item_completed", lambda _item: None)
    task = (
        await work_item_client.post(
            "/v1/work-items",
            json={"title": "Legacy", "assignee_agent_id": agent_id},
        )
    ).json()
    completed = (
        await work_item_client.patch(
            f"/v1/work-items/{task['id']}",
            json={"state": "done", "expected_version": 1},
        )
    ).json()
    with get_or_create_engine(db_uri).begin() as connection:
        connection.execute(
            update(SqlWorkItem)
            .where(
                SqlWorkItem.workspace_id == current_workspace_id(),
                SqlWorkItem.id == task["id"],
            )
            .values(completion_id=None)
        )
    SqlAlchemyInboxItemStore(db_uri).create_if_absent(
        "f" * 32,
        owner_user_id=None,
        kind="task_completed",
        dedupe_key=f"local:work-item:{task['id']}:completed:{completed['version']}",
        work_item_id=task["id"],
        message="Legacy",
        target_url=f"/tasks/{task['id']}",
    )
    run = (
        await work_item_client.post(
            f"/v1/work-items/{task['id']}/runs",
            json={"runtime_id": "runtime-local", "workspace": "/tmp/orvia-task"},
        )
    ).json()
    SqlAlchemyWorkItemRunStore(db_uri).transition(run["id"], state="succeeded")

    first = (await work_item_client.get("/v1/inbox-items")).json()
    second = (await work_item_client.get("/v1/inbox-items")).json()
    assert {(row["kind"], row["message"]) for row in first["data"]} == {
        ("task_completed", "Legacy"),
        ("task_succeeded", "Legacy"),
    }
    assert {row["id"] for row in second["data"]} == {row["id"] for row in first["data"]}


async def test_confirmation_and_session_completion_are_persistent_and_deduplicated(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    from omnigent.server import session_live_state

    conversation = SqlAlchemyConversationStore(db_uri).create_conversation(title="Review session")
    approval = {
        "type": "response.elicitation_request",
        "elicitation_id": "approval-1",
        "params": {"message": "Allow this command?"},
    }
    session_live_state.persist_inbox_elicitation(conversation.id, approval)
    session_live_state.persist_inbox_elicitation(conversation.id, approval)
    session_live_state.persist_work_item_run_status(
        conversation.id,
        "idle",
        response_id="response-1",
    )

    for _ in range(20):
        rows = (await work_item_client.get("/v1/inbox-items")).json()["data"]
        if len(rows) == 2:
            break
        await asyncio.sleep(0.01)
    assert {row["kind"] for row in rows} == {"approval_required", "session_completed"}
    assert len([row for row in rows if row["source_id"] == "approval-1"]) == 1

    session_live_state.persist_inbox_elicitation(
        conversation.id,
        {"type": "response.elicitation_resolved", "elicitation_id": "approval-1"},
    )
    for _ in range(20):
        rows = (await work_item_client.get("/v1/inbox-items")).json()["data"]
        approval_row = next(row for row in rows if row["source_id"] == "approval-1")
        if approval_row["resolved_at"] is not None:
            break
        await asyncio.sleep(0.01)
    assert approval_row["action_required"] is False
    assert approval_row["resolved_at"] is not None


async def test_project_reference_must_be_owned_and_is_cleared_on_project_delete(
    work_item_client: httpx.AsyncClient,
) -> None:
    project = (await work_item_client.post("/v1/projects", json={"name": "Alpha"})).json()
    created = (
        await work_item_client.post(
            "/v1/work-items",
            json={"title": "Project task", "project_id": project["id"]},
        )
    ).json()
    assert created["project_id"] == project["id"]

    deleted = await work_item_client.delete(f"/v1/projects/{project['id']}")
    assert deleted.status_code == 200
    preserved = (await work_item_client.get(f"/v1/work-items/{created['id']}")).json()
    assert preserved["project_id"] is None

    unknown = await work_item_client.post(
        "/v1/work-items",
        json={"title": "Bad project", "project_id": "0" * 32},
    )
    assert unknown.status_code == 404


async def test_invalid_task_fields_are_rejected(work_item_client: httpx.AsyncClient) -> None:
    empty_title = await work_item_client.post("/v1/work-items", json={"title": "   "})
    assert empty_title.status_code == 422
    assert (
        await work_item_client.post("/v1/work-items", json={"title": "X", "state": "not-a-state"})
    ).status_code == 422
    assert (
        await work_item_client.post("/v1/work-items", json={"title": "X", "priority": "critical"})
    ).status_code == 422


async def test_work_items_are_owner_private(
    runtime_init: None,
    db_uri: str,
    tmp_path: Path,
) -> None:
    auth = UnifiedAuthProvider(source="header", local_single_user=False)
    transport = httpx.ASGITransport(app=_build_app(db_uri, tmp_path, auth_provider=auth))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        alice_headers = {"X-Forwarded-Email": "alice@example.com"}
        bob_headers = {"X-Forwarded-Email": "bob@example.com"}
        task = (
            await client.post(
                "/v1/work-items",
                json={"title": "Alice only"},
                headers=alice_headers,
            )
        ).json()

        assert (await client.get("/v1/work-items", headers=bob_headers)).json()["data"] == []
        assert (
            await client.get(f"/v1/work-items/{task['id']}", headers=bob_headers)
        ).status_code == 404
        assert (
            await client.patch(
                f"/v1/work-items/{task['id']}",
                json={"state": "todo", "expected_version": 1},
                headers=bob_headers,
            )
        ).status_code == 404
        assert (
            await client.patch(
                f"/v1/work-items/{task['id']}",
                json={"state": "done", "expected_version": 1},
                headers=alice_headers,
            )
        ).status_code == 200
        for _ in range(20):
            alice_inbox = (await client.get("/v1/inbox-items", headers=alice_headers)).json()
            if alice_inbox["data"]:
                break
            await asyncio.sleep(0.01)
        assert alice_inbox["unread_count"] == 1
        assert (await client.get("/v1/inbox-items", headers=bob_headers)).json()["data"] == []


async def test_task_run_creates_real_session_binding_and_keeps_retry_history(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch,
) -> None:
    agent_id = "a" * 32
    SqlAlchemyAgentStore(db_uri).create(
        agent_id,
        name="test-runner",
        bundle_location="test:///bundle",
    )
    session_ids = iter(("b" * 32, "c" * 32))

    async def create_session(_self, command):
        assert command.runtime_id == "runtime-local"
        assert command.workspace == "/tmp/orvia-task"
        return next(session_ids)

    async def send_input(_self, session_id, event, _actor_id):
        assert session_id in {"b" * 32, "c" * 32}
        assert event.type == "message"

    monkeypatch.setattr(ASGISessionGateway, "create_task_session", create_session)
    monkeypatch.setattr(ASGISessionGateway, "send_input", send_input)

    task = (
        await work_item_client.post(
            "/v1/work-items",
            json={"title": "Execute me", "assignee_agent_id": agent_id},
        )
    ).json()
    first_response = await work_item_client.post(
        f"/v1/work-items/{task['id']}/runs",
        json={"runtime_id": "runtime-local", "workspace": "/tmp/orvia-task"},
    )
    assert first_response.status_code == 201
    first = first_response.json()
    assert first["state"] == "running"
    assert first["session_id"] == "b" * 32
    assert first["usage_refs"] == [f"session:{'b' * 32}"]

    store = SqlAlchemyWorkItemRunStore(db_uri)
    failed = store.transition(
        first["id"],
        state="failed",
        failure_code="runner_error",
        failure_message="boom",
        failure_retryable=True,
    )
    assert failed is not None

    retry_response = await work_item_client.post(
        f"/v1/work-items/{task['id']}/runs",
        json={
            "runtime_id": "runtime-local",
            "workspace": "/tmp/orvia-task",
            "retry_of_run_id": first["id"],
        },
    )
    assert retry_response.status_code == 201
    retry = retry_response.json()
    assert retry["id"] != first["id"]
    assert retry["trigger"] == "retry"
    assert retry["retry_of_run_id"] == first["id"]

    history = (await work_item_client.get(f"/v1/work-items/{task['id']}/runs")).json()
    assert [run["id"] for run in history["data"]] == [retry["id"], first["id"]]


async def test_inbox_read_repair_recovers_a_missing_terminal_run_projection(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch,
) -> None:
    agent_id = "d" * 32
    SqlAlchemyAgentStore(db_uri).create(
        agent_id,
        name="repair-runner",
        bundle_location="test:///bundle",
    )

    async def create_session(_self, _command):
        return "e" * 32

    async def send_input(_self, _session_id, _event, _actor_id):
        return None

    monkeypatch.setattr(ASGISessionGateway, "create_task_session", create_session)
    monkeypatch.setattr(ASGISessionGateway, "send_input", send_input)

    task = (
        await work_item_client.post(
            "/v1/work-items",
            json={"title": "Recover projection", "assignee_agent_id": agent_id},
        )
    ).json()
    run = (
        await work_item_client.post(
            f"/v1/work-items/{task['id']}/runs",
            json={"runtime_id": "runtime-local", "workspace": "/tmp/orvia-task"},
        )
    ).json()
    SqlAlchemyWorkItemRunStore(db_uri).transition(run["id"], state="succeeded")
    assert SqlAlchemyInboxItemStore(db_uri).list(owner_user_id=None) == []

    first = (await work_item_client.get("/v1/inbox-items")).json()
    assert [(row["kind"], row["message"]) for row in first["data"]] == [
        ("task_succeeded", "Recover projection")
    ]
    assert first["unread_count"] == 1

    second = (await work_item_client.get("/v1/inbox-items")).json()
    assert [row["id"] for row in second["data"]] == [row["id"] for row in first["data"]]
    assert second["unread_count"] == 1


async def test_task_run_launch_failure_is_persisted(
    work_item_client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch,
) -> None:
    agent_id = "d" * 32
    SqlAlchemyAgentStore(db_uri).create(
        agent_id,
        name="offline-runner",
        bundle_location="test:///bundle",
    )

    async def fail_create(_self, _command):
        raise OmnigentError("Host is offline", code=ErrorCode.RUNNER_UNAVAILABLE)

    monkeypatch.setattr(ASGISessionGateway, "create_task_session", fail_create)
    task = (
        await work_item_client.post(
            "/v1/work-items",
            json={"title": "Keep failure", "assignee_agent_id": agent_id},
        )
    ).json()
    response = await work_item_client.post(
        f"/v1/work-items/{task['id']}/runs",
        json={"runtime_id": "offline", "workspace": "/tmp/orvia-task"},
    )

    assert response.status_code == 201
    run = response.json()
    assert run["state"] == "failed"
    assert run["session_id"] is None
    assert run["failure"] == {
        "code": "runner_unavailable",
        "message": "Host is offline",
        "retryable": True,
    }
    assert (await work_item_client.get(f"/v1/work-items/{task['id']}/runs")).json()["data"] == [
        run
    ]
