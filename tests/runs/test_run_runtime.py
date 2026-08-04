from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from omnigent.db.db_models import OmnigentBase
from omnigent.db.utils import get_or_create_engine
from omnigent.entities import Agent
from omnigent.entities.run_projection import (
    AttemptStatus,
    ProjectionEvent,
    RunCreate,
    RunStatus,
)
from omnigent.runs.projection import RunProjector
from omnigent.runs.service import RunService
from omnigent.server.schemas import SessionEventInput
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore
from omnigent.workspaces.manifest import WorkspaceRepository
from omnigent.workspaces.worktree_lease import WorktreeLeaseManager


@pytest.fixture()
def database(tmp_path: Path) -> str:
    uri = f"sqlite:///{tmp_path / 'runs.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(uri))
    return uri


def _create_workspace(store: SqlAlchemyRunStore, root: Path):
    api = root / "api"
    web = root / "web"
    api.mkdir(parents=True)
    web.mkdir()
    (api / ".git").mkdir()
    (web / ".git").mkdir()
    return store.create_workspace(
        root_path=str(root),
        repositories=(
            ("api", "api"),
            ("web", "web"),
        ),
    )


def _create_run(store: SqlAlchemyRunStore, workspace_id: str):
    return store.create_run_idempotent(
        auth_scope="user:alice",
        actor_id="alice@example.com",
        source="api.webhook-v1",
        source_event_id="event-1",
        agent_id="a" * 32,
        bundle_version=7,
        bundle_digest="b" * 64,
        bundle_location=f"{'a' * 32}/{'b' * 64}",
        workspace_id=workspace_id,
        root_session_id="c" * 32,
    )


def test_external_idempotency_and_run_snapshot_are_durable(database: str, tmp_path: Path) -> None:
    store = SqlAlchemyRunStore(database)
    workspace = _create_workspace(store, tmp_path / "中文项目")

    first = _create_run(store, workspace.id)
    second = _create_run(store, workspace.id)

    assert first.created is True
    assert second.created is False
    assert second.run == first.run
    assert first.run.agent_id == "a" * 32
    assert first.run.bundle_version == 7
    assert first.run.bundle_digest == "b" * 64
    assert first.run.bundle_location == f"{'a' * 32}/{'b' * 64}"
    assert first.run.workspace_id == workspace.id
    assert [repo.path for repo in store.get_workspace(workspace.id).repositories] == [
        "api",
        "web",
    ]


def test_projection_replay_dispatch_attempts_and_explicit_dependencies(
    database: str, tmp_path: Path
) -> None:
    store = SqlAlchemyRunStore(database)
    run = _create_run(store, _create_workspace(store, tmp_path / "workspace").id).run
    projector = RunProjector(store)

    first = ProjectionEvent(
        source="session",
        source_event_id="dispatch-1",
        event_type="dispatch.created",
        run_id=run.id,
        session_id=run.root_session_id,
        payload={
            "worker_name": "coder",
            "title": "API implementation",
            "child_session_id": "d" * 32,
            "dispatch_call_id": "call-1",
        },
    )
    assert projector.apply(first).created is True
    assert projector.apply(first).created is False

    second = replace(
        first,
        source_event_id="dispatch-2",
        payload={
            "worker_name": "coder",
            "title": "Web implementation",
            "child_session_id": "e" * 32,
            "dispatch_call_id": "call-2",
        },
    )
    repeated_title = replace(
        first,
        source_event_id="dispatch-3",
        payload={
            "worker_name": "coder",
            "title": "API implementation",
            "child_session_id": "d" * 32,
            "dispatch_call_id": "call-3",
        },
    )
    projector.apply(second)
    projector.apply(repeated_title)

    tasks = store.list_tasks(run.id)
    attempts = store.list_attempts(run.id)
    assert len(tasks) == 2
    assert len(attempts) == 3
    assert len({task.id for task in tasks}) == 2
    assert {attempt.child_session_id for attempt in attempts} == {
        "d" * 32,
        "e" * 32,
    }
    assert store.list_dependencies(run.id) == ()

    dependency = ProjectionEvent(
        source="session",
        source_event_id="plan-1",
        event_type="plan.dependency",
        run_id=run.id,
        session_id=run.root_session_id,
        payload={"task_id": tasks[1].id, "depends_on_task_id": tasks[0].id},
    )
    projector.apply(dependency)
    assert store.list_dependencies(run.id) == ((tasks[1].id, tasks[0].id),)


def test_inspector_links_real_sessions_items_and_failure_reason(
    database: str, tmp_path: Path
) -> None:
    store = SqlAlchemyRunStore(database)
    run = _create_run(store, _create_workspace(store, tmp_path / "workspace").id).run
    projector = RunProjector(store)
    dispatch = ProjectionEvent(
        source="session",
        source_event_id="dispatch-failed",
        event_type="dispatch.created",
        run_id=run.id,
        session_id=run.root_session_id,
        conversation_item_id="3" * 32,
        payload={
            "worker_name": "reviewer",
            "title": "Review",
            "child_session_id": "d" * 32,
            "dispatch_call_id": "call-failed",
        },
    )
    result = projector.apply(dispatch)
    assert result.attempt is not None
    projector.apply(
        ProjectionEvent(
            source="session",
            source_event_id="terminal-failed",
            event_type="session.failed",
            run_id=run.id,
            task_id=result.task.id,
            attempt_id=result.attempt.id,
            session_id="d" * 32,
            conversation_item_id="4" * 32,
            payload={"failure_code": "runner_crashed", "failure_message": "exit code 137"},
        )
    )

    inspector = store.inspect_run(run.id)

    assert inspector.root_session_id == run.root_session_id
    assert inspector.child_session_ids == ("d" * 32,)
    assert inspector.conversation_item_ids == ("3" * 32, "4" * 32)
    assert inspector.failures[0].code == "runner_crashed"
    assert inspector.failures[0].message == "exit code 137"
    assert inspector.attempts[0].status is AttemptStatus.FAILED


def test_durable_worktree_lease_recovers_and_prevents_path_collision(
    database: str, tmp_path: Path
) -> None:
    store = SqlAlchemyRunStore(database)
    run = _create_run(store, _create_workspace(store, tmp_path / "workspace").id).run
    lease = store.acquire_worktree_lease(
        run_id=run.id,
        attempt_id="1" * 32,
        child_session_id="2" * 32,
        host_id="host-1",
        repository_id="api",
        worktree_path="/worktrees/api-attempt-1",
        branch="omnigent/attempt-1/api",
        owner_id="runner-1",
        base_commit="a" * 40,
    )

    restarted = SqlAlchemyRunStore(database)
    assert restarted.list_active_worktree_leases(run.id) == (lease,)
    with pytest.raises(ValueError, match="already leased"):
        restarted.acquire_worktree_lease(
            run_id=run.id,
            attempt_id="3" * 32,
            child_session_id="4" * 32,
            host_id="host-1",
            repository_id="api",
            worktree_path=lease.worktree_path,
            branch="omnigent/attempt-2/api",
            owner_id="runner-2",
        )
    restarted.release_worktree_lease(lease.id, owner_id="runner-1", output_commit="b" * 40)
    assert restarted.list_active_worktree_leases(run.id) == ()


@pytest.mark.asyncio
async def test_run_service_creates_one_pinned_root_session_and_submits_one_input(
    database: str, tmp_path: Path
) -> None:
    run_store = SqlAlchemyRunStore(database)
    conversation_store = SqlAlchemyConversationStore(database)
    workspace = _create_workspace(run_store, tmp_path / "workspace")
    digest = "9" * 64
    agent = Agent(
        id="8" * 32,
        created_at=1,
        name="coordinator",
        version=4,
        bundle_location=f"{'8' * 32}/{digest}",
    )

    class _Agents:
        @staticmethod
        def get(agent_id: str) -> Agent | None:
            return agent if agent_id == agent.id else None

    submitted: list[tuple[str, SessionEventInput, str]] = []

    async def submit(session_id: str, event: SessionEventInput, actor_id: str) -> None:
        submitted.append((session_id, event, actor_id))

    service = RunService(
        run_store=run_store,
        conversation_store=conversation_store,
        agent_store=_Agents(),
        submit_session_event=submit,
    )
    command = RunCreate(
        agent_id=agent.id,
        workspace_id=workspace.id,
        input="Coordinate the implementation",
        source="api:request-v1",
        source_event_id="request-42",
        host_id=None,
        execution_mode="auto",
    )

    first = await service.create(command, actor_id="alice@example.com", auth_scope="user:alice")
    second = await service.create(command, actor_id="alice@example.com", auth_scope="user:alice")

    assert first.created is True
    assert second.created is False
    assert second.run.id == first.run.id
    root = conversation_store.get_conversation(first.run.root_session_id)
    assert root is not None
    assert root.agent_id == agent.id
    assert root.agent_bundle_version == 4
    assert root.agent_bundle_digest == digest
    assert root.agent_bundle_location == agent.bundle_location
    assert root.workspace == str((tmp_path / "workspace").resolve())
    assert [(session_id, event.type, actor_id) for session_id, event, actor_id in submitted] == [
        (root.id, "message", "alice@example.com")
    ]
    assert submitted[0][1].data["content"][0]["text"] == "Coordinate the implementation"
    assert first.run.status is RunStatus.RUNNING


@pytest.mark.asyncio
async def test_worktree_manager_mirrors_acquire_and_release_to_durable_store(
    database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyRunStore(database)
    run = _create_run(store, _create_workspace(store, tmp_path / "workspace").id).run

    class _Created:
        worktree_path = "/worktrees/api-attempt"
        branch = "omnigent/attempt/api"

    async def create(**kwargs: object) -> _Created:
        return _Created()

    async def remove(**kwargs: object) -> None:
        return None

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    manager = WorktreeLeaseManager(ttl_s=60, durable_store=store)
    host = type("Host", (), {"host_id": "host-1"})()

    leases = await manager.acquire(
        host_id="host-1",
        host_registry=object(),
        host_conn=host,
        workspace_root=tmp_path / "workspace",
        repositories=(WorkspaceRepository(id="api", path="api"),),
        run_id=run.id,
        attempt_id="5" * 32,
        child_session_id="6" * 32,
        owner_id="runner-1",
    )

    durable = store.list_active_worktree_leases(run.id)
    assert len(durable) == 1
    assert durable[0].worktree_path == leases[0].worktree_path
    await manager.release(
        host_registry=object(), host_conn=host, leases=leases, owner_id="runner-1"
    )
    assert store.list_active_worktree_leases(run.id) == ()
