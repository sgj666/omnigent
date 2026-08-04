from __future__ import annotations

import asyncio
import hashlib
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from omnigent.db.db_models import OmnigentBase
from omnigent.db.utils import get_or_create_engine
from omnigent.entities import Agent
from omnigent.entities.run_projection import (
    AttemptStatus,
    ProjectionEvent,
    RunCreate,
    RunStatus,
    TaskStatus,
    WorktreeLeaseStatus,
)
from omnigent.errors import OmnigentError
from omnigent.runs.projection import RunProjector
from omnigent.runs.service import RootSessionRequest, RunService
from omnigent.runs.session_gateway import ASGISessionGateway
from omnigent.server.schemas import SessionEventInput
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore
from omnigent.workspaces.manifest import WorkspaceRepository
from omnigent.workspaces.worktree_lease import LeaseStatus, WorktreeLeaseManager


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


def test_reserved_child_dispatch_reuses_real_attempt_on_accept(
    database: str, tmp_path: Path
) -> None:
    store = SqlAlchemyRunStore(database)
    run = _create_run(store, _create_workspace(store, tmp_path / "workspace").id).run
    child_id = "d" * 32

    reserved = store.reserve_child_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        worker_name="coder",
        title="Implement API",
        source_id="sys_session_send:stable",
    )
    replay = store.reserve_child_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        worker_name="coder",
        title="Implement API",
        source_id="sys_session_send:stable",
    )
    assert reserved.attempt is not None
    assert reserved.attempt.status is AttemptStatus.QUEUED
    assert replay.created is False
    assert replay.attempt == reserved.attempt
    item_id = "e" * 32

    accepted = store.apply_projection_event(
        ProjectionEvent(
            source="session-runtime",
            source_event_id=f"dispatch:{child_id}:{item_id}",
            event_type="dispatch.created",
            run_id=run.id,
            session_id=child_id,
            conversation_item_id=item_id,
            payload={
                "worker_name": "coder",
                "title": "Implement API",
                "child_session_id": child_id,
                "dispatch_call_id": item_id,
            },
        )
    )

    assert accepted.attempt is not None
    assert accepted.attempt.id == reserved.attempt.id
    assert accepted.attempt.status is AttemptStatus.RUNNING
    assert len(store.list_attempts(run.id)) == 1


def test_followup_reservation_reuses_task_and_is_source_idempotent(
    database: str, tmp_path: Path
) -> None:
    store = SqlAlchemyRunStore(database)
    run = _create_run(store, _create_workspace(store, tmp_path / "workspace").id).run
    child_id = "d" * 32
    first = store.reserve_child_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        worker_name="coder",
        title="Implement API",
        source_id="initial",
    )
    assert first.task is not None
    assert first.attempt is not None
    store.apply_projection_event(
        ProjectionEvent(
            source="session-runtime",
            source_event_id="dispatch:first",
            event_type="dispatch.created",
            run_id=run.id,
            session_id=child_id,
            payload={
                "worker_name": "coder",
                "title": "Implement API",
                "child_session_id": child_id,
                "dispatch_call_id": "first",
            },
        )
    )
    store.apply_projection_event(
        ProjectionEvent(
            source="session-runtime",
            source_event_id=f"complete:{first.attempt.id}",
            event_type="session.completed",
            run_id=run.id,
            task_id=first.task.id,
            attempt_id=first.attempt.id,
            session_id=child_id,
        )
    )

    followup = store.reserve_followup_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        source_id="followup-1",
    )
    replay = store.reserve_followup_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        source_id="followup-1",
    )

    assert followup.created is True
    assert followup.task is not None
    assert followup.task.id == first.task.id
    assert followup.attempt is not None
    assert followup.attempt.id != first.attempt.id
    assert followup.attempt.status is AttemptStatus.QUEUED
    assert replay.created is False
    assert replay.attempt == followup.attempt
    assert len(store.list_tasks(run.id)) == 1
    assert len(store.list_attempts(run.id)) == 2


def test_followup_dispatch_claim_is_durable_across_store_instances(
    database: str, tmp_path: Path
) -> None:
    store_a = SqlAlchemyRunStore(database)
    store_b = SqlAlchemyRunStore(database)
    run = _create_run(store_a, _create_workspace(store_a, tmp_path / "workspace").id).run
    child_id = "d" * 32
    first = store_a.reserve_child_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        worker_name="coder",
        title="Implement API",
        source_id="initial",
    )
    assert first.task is not None
    assert first.attempt is not None
    store_a.apply_projection_event(
        ProjectionEvent(
            source="session-runtime",
            source_event_id="dispatch:first",
            event_type="dispatch.created",
            run_id=run.id,
            session_id=child_id,
            payload={
                "worker_name": "coder",
                "title": "Implement API",
                "child_session_id": child_id,
                "dispatch_call_id": "first",
            },
        )
    )
    store_a.apply_projection_event(
        ProjectionEvent(
            source="session-runtime",
            source_event_id=f"complete:{first.attempt.id}",
            event_type="session.completed",
            run_id=run.id,
            task_id=first.task.id,
            attempt_id=first.attempt.id,
            session_id=child_id,
        )
    )
    reserved = store_a.reserve_followup_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        source_id="followup-concurrent",
    )
    assert reserved.attempt is not None
    idempotency_key = "f" * 32
    barrier = threading.Barrier(2)
    phases: list[tuple[str, str]] = []
    errors: list[BaseException] = []
    result_lock = threading.Lock()

    def _claim(store: SqlAlchemyRunStore) -> None:
        try:
            barrier.wait()
            phase, attempt = store.claim_followup_dispatch(
                run_id=run.id,
                child_session_id=child_id,
                source_id="followup-concurrent",
                idempotency_key=idempotency_key,
            )
            with result_lock:
                phases.append((phase, attempt.id))
        except BaseException as exc:
            with result_lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=_claim, args=(store,))
        for store in (store_a, store_b)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(phase for phase, _attempt_id in phases) == ["claimed", "dispatching"]
    assert {attempt_id for _phase, attempt_id in phases} == {reserved.attempt.id}

    accepted = store_b.accept_followup_dispatch(
        run_id=run.id,
        attempt_id=reserved.attempt.id,
        idempotency_key=idempotency_key,
    )
    assert accepted.status is AttemptStatus.RUNNING
    replay_phase, replay_attempt = store_a.claim_followup_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        source_id="followup-concurrent",
        idempotency_key=idempotency_key,
    )
    assert replay_phase == "accepted"
    assert replay_attempt.id == reserved.attempt.id

    projected = store_a.apply_projection_event(
        ProjectionEvent(
            source="session-runtime",
            source_event_id="dispatch:followup-concurrent",
            event_type="dispatch.created",
            run_id=run.id,
            session_id=child_id,
            conversation_item_id=idempotency_key,
            payload={
                "worker_name": "coder",
                "title": "Implement API",
                "child_session_id": child_id,
                "dispatch_call_id": idempotency_key,
            },
        )
    )
    assert projected.attempt is not None
    assert projected.attempt.id == reserved.attempt.id
    assert len(store_a.list_tasks(run.id)) == 1
    assert len(store_a.list_attempts(run.id)) == 2


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_point",
    ("none", "before_parent", "before_cleanup"),
)
async def test_indeterminate_dispatch_failure_projects_run_wakes_parent_and_defers_lease(
    db_uri: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """The production receipt callback terminalizes every durable Run surface."""
    from omnigent.entities import MessageData, NewConversationItem
    from omnigent.runtime.agent_cache import AgentCache
    from omnigent.server.app import create_app
    from omnigent.server.routes._host_worktree import (
        configure_attempt_worktree_lease_store,
    )
    from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
    from omnigent.stores.artifact_store.local import LocalArtifactStore
    from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore

    conversations = SqlAlchemyConversationStore(db_uri)
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=conversations,
        artifact_store=artifacts,
        agent_cache=AgentCache(artifact_store=artifacts, cache_dir=tmp_path / "cache"),
        runner_tunnel_tokens=frozenset({"test-runner-token"}),
    )
    run_store = app.state.run_store
    workspace = _create_workspace(run_store, tmp_path / "workspace")
    run = _create_run(run_store, workspace.id).run
    root_id = run.root_session_id
    assert root_id is not None
    child_id = "d" * 32
    runner_id = "runner-indeterminate"
    key = "7" * 32
    conversations.create_conversation(
        conversation_id=root_id,
        agent_id=run.agent_id,
        agent_bundle_version=run.bundle_version,
        agent_bundle_digest=run.bundle_digest,
        agent_bundle_location=run.bundle_location,
    )
    child = conversations.create_conversation(
        conversation_id=child_id,
        parent_conversation_id=root_id,
        kind="sub_agent",
        sub_agent_name="worker",
        title="worker: indeterminate task",
        runner_id=runner_id,
    )
    persisted = conversations.append_idempotent(
        child_id,
        [
            NewConversationItem(
                type="message",
                response_id="turn_indeterminate",
                data=MessageData(
                    role="user",
                    content=[{"type": "input_text", "text": "side effect"}],
                ),
            )
        ],
        idempotency_key=key,
    )[0]
    reserved = run_store.reserve_child_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        worker_name="worker",
        title="indeterminate task",
        source_id="dispatch-indeterminate",
    )
    assert reserved.attempt is not None
    accepted = app.state.run_projection.dispatch_accepted(
        child,
        conversation_item_id=persisted.id,
    )
    assert accepted is not None
    assert accepted.attempt is not None
    attempt_id = accepted.attempt.id
    run_store.acquire_worktree_lease(
        run_id=run.id,
        attempt_id=attempt_id,
        child_session_id=child_id,
        host_id="host-indeterminate",
        repository_id=workspace.repositories[0].id,
        worktree_path="/worktrees/indeterminate",
        branch="omnigent/attempt/indeterminate",
        owner_id=runner_id,
    )
    # Rehydrate the process-wide production manager after seeding the durable lease.
    configure_attempt_worktree_lease_store(run_store)
    removed_worktrees: list[str] = []

    async def _record_remove(**kwargs: object) -> None:
        removed_worktrees.append(str(kwargs["worktree_path"]))

    monkeypatch.setattr(
        "omnigent.workspaces.worktree_lease.remove_worktree_on_host",
        _record_remove,
    )
    conversations.claim_runner_dispatch_receipt(
        child_id,
        idempotency_key=key,
        runner_id=runner_id,
        persisted_item_id=persisted.id,
        execution_owner_id="old-generation",
    )
    running = conversations.transition_runner_dispatch_receipt(
        child_id,
        idempotency_key=key,
        runner_id=runner_id,
        execution_owner_id="old-generation",
        expected_phases=("queued",),
        phase="running",
    )
    assert running is not None

    wake_calls: list[tuple[str, str]] = []
    delivered_sources: set[str] = set()
    wake_attempts = 0

    async def _record_parent_wake(
        session_id: str,
        _child: object,
        error: Any,
        _runner_router: object,
        **_kwargs: object,
    ) -> None:
        nonlocal wake_attempts
        wake_attempts += 1
        if failure_point == "before_parent" and wake_attempts == 1:
            raise RuntimeError("crash after Run projection before Parent relay")
        wake_calls.append((session_id, str(error.code)))
        source = _kwargs.get("source_event_id")
        assert isinstance(source, str)
        assert _kwargs.get("require_wake_ack") is True
        delivered_sources.add(source)

    monkeypatch.setattr(
        "omnigent.server.routes._sessions.orchestration."
        "_forward_native_subagent_terminal_failure",
        _record_parent_wake,
    )
    from omnigent.server.routes._sessions import orchestration as orchestration_module

    real_cleanup = orchestration_module._cleanup_projected_run_attempt
    cleanup_attempts = 0

    async def _crashable_cleanup(*args: object, **kwargs: object) -> None:
        nonlocal cleanup_attempts
        cleanup_attempts += 1
        if failure_point == "before_cleanup" and cleanup_attempts == 1:
            raise RuntimeError("crash after Parent relay before lease cleanup")
        await real_cleanup(*args, **kwargs)

    monkeypatch.setattr(
        orchestration_module,
        "_cleanup_projected_run_attempt",
        _crashable_cleanup,
    )
    transition = {
        "conversation_id": child_id,
        "idempotency_key": key,
        "runner_id": runner_id,
        "execution_owner_id": "new-generation",
        "expected_phases": ["running"],
        "phase": "failed",
        "result": {
            "status": "failed",
            "failure_code": "runner_restarted_during_execution",
            "detail": "execution outcome is indeterminate",
        },
        "allow_takeover": True,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://ap",
        headers={
            "X-Omnigent-Runner-Tunnel-Token": "test-runner-token",
            "X-Omnigent-Runner-Id": runner_id,
        },
    ) as client:
        response = await client.post(
            "/v1/runner-dispatch-receipts/transition",
            json=transition,
        )
        replay = await client.post(
            "/v1/runner-dispatch-receipts/transition",
            json=transition,
        )

    assert response.status_code == 200, response.text
    expected_initial_effects = "completed" if failure_point == "none" else "pending"
    assert response.json()["effects_status"] == expected_initial_effects
    assert replay.status_code == 409
    if failure_point != "none":
        restarted_conversations = SqlAlchemyConversationStore(db_uri)
        restarted_app = create_app(
            agent_store=SqlAlchemyAgentStore(db_uri),
            file_store=SqlAlchemyFileStore(db_uri),
            conversation_store=restarted_conversations,
            artifact_store=artifacts,
            agent_cache=AgentCache(
                artifact_store=artifacts,
                cache_dir=tmp_path / "restarted-cache",
            ),
            runner_tunnel_tokens=frozenset({"test-runner-token"}),
        )
        drained = await restarted_app.state.replay_pending_runner_dispatch_effects()
        assert len(drained) == 1
        assert drained[0]["effects_status"] == "completed"
        completed_receipt = restarted_conversations.get_runner_dispatch_receipt(
            child_id,
            idempotency_key=key,
        )
        assert completed_receipt is not None
        assert completed_receipt["effects_status"] == "completed"
        assert completed_receipt["effects_attempt_count"] == 2
    expected_source = hashlib.sha256(f"{child_id}\0{key}".encode()).hexdigest()
    assert delivered_sources == {f"dispatch-effects:{expected_source}"}
    assert wake_calls[-1] == (child_id, "runner_restarted_during_execution")
    task, attempt = run_store.get_latest_attempt_for_child(run.id, child_id)
    assert task.status is TaskStatus.FAILED
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.failure_code == "runner_restarted_during_execution"
    assert run_store.get_run(run.id).status is RunStatus.FAILED
    leases = run_store.list_active_worktree_leases(run.id)
    assert len(leases) == 1
    assert leases[0].status is WorktreeLeaseStatus.RECOVERY_REQUIRED
    assert removed_worktrees == []


@pytest.mark.asyncio
async def test_max_length_dispatch_key_replays_wake_with_bounded_stable_source(
    db_uri: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 128-character receipt key cannot make Parent wake permanently 422."""
    import json

    from omnigent.entities import MessageData, NewConversationItem
    from omnigent.runner import app as runner_app_module
    from omnigent.runner import create_runner_app
    from omnigent.runtime.agent_cache import AgentCache
    from omnigent.server.app import create_app
    from omnigent.server.routes import sessions as sessions_module
    from omnigent.server.routes.sessions import _RunnerForwardResult
    from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
    from omnigent.stores.artifact_store.local import LocalArtifactStore
    from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
    from tests.runner.conftest import _FakeProcessManager, _ScriptedHarnessClient

    conversations = SqlAlchemyConversationStore(db_uri)
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=conversations,
        artifact_store=artifacts,
        agent_cache=AgentCache(artifact_store=artifacts, cache_dir=tmp_path / "cache"),
        runner_tunnel_tokens=frozenset({"test-runner-token"}),
    )
    parent_id = "a" * 32
    child_id = "b" * 32
    runner_id = "runner-max-source"
    key = "k" * 128
    conversations.create_conversation(
        conversation_id=parent_id,
        agent_id="c" * 32,
        agent_bundle_version=1,
        agent_bundle_digest="d" * 64,
        agent_bundle_location=f"{'c' * 32}/{'d' * 64}",
    )
    conversations.create_conversation(
        conversation_id=child_id,
        parent_conversation_id=parent_id,
        kind="sub_agent",
        sub_agent_name="worker",
        title="worker: max source",
        runner_id=runner_id,
    )
    persisted = conversations.append_idempotent(
        child_id,
        [
            NewConversationItem(
                type="message",
                response_id="turn_max_source",
                data=MessageData(
                    role="user",
                    content=[{"type": "input_text", "text": "side effect"}],
                ),
            )
        ],
        idempotency_key=key,
    )[0]
    conversations.claim_runner_dispatch_receipt(
        child_id,
        idempotency_key=key,
        runner_id=runner_id,
        persisted_item_id=persisted.id,
        execution_owner_id="old-generation",
    )
    running = conversations.transition_runner_dispatch_receipt(
        child_id,
        idempotency_key=key,
        runner_id=runner_id,
        execution_owner_id="old-generation",
        expected_phases=("queued",),
        phase="running",
    )
    assert running is not None

    wake_bodies: list[dict[str, Any]] = []

    async def _wake_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        wake_bodies.append(body)
        source = body.get("dispatch_source_id")
        if not isinstance(source, str) or len(source) > 128:
            return httpx.Response(422, request=request)
        return httpx.Response(503 if len(wake_bodies) <= 3 else 200, request=request)

    async def _no_wake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(runner_app_module, "_wake_retry_sleep", _no_wake_sleep)
    wake_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_wake_handler),
        base_url="http://ap",
    )
    runner = create_runner_app(
        process_manager=_FakeProcessManager(_ScriptedHarnessClient([])),  # type: ignore[arg-type]
        server_client=wake_client,
    )
    parent_inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    runner_app_module._session_inboxes_ref[parent_id] = parent_inbox
    runner_app_module.register_subagent_work(
        parent_session_id=parent_id,
        child_session_id=child_id,
        agent="worker",
        title="max-source",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runner),
        base_url="http://runner",
    ) as runner_client:

        async def _forward_to_runner(
            session_id: str,
            _runner_router: object,
            event: dict[str, Any],
        ) -> _RunnerForwardResult:
            response = await runner_client.post(
                f"/v1/sessions/{session_id}/events",
                json=event,
            )
            return _RunnerForwardResult(
                status_code=response.status_code,
                body=response.text,
            )

        monkeypatch.setattr(
            sessions_module,
            "_forward_session_change_to_runner",
            _forward_to_runner,
        )
        transition = {
            "conversation_id": child_id,
            "idempotency_key": key,
            "runner_id": runner_id,
            "execution_owner_id": "new-generation",
            "expected_phases": ["running"],
            "phase": "failed",
            "result": {
                "status": "failed",
                "failure_code": "runner_restarted_during_execution",
                "detail": "execution outcome is indeterminate",
            },
            "allow_takeover": True,
        }
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://ap",
                headers={
                    "X-Omnigent-Runner-Tunnel-Token": "test-runner-token",
                    "X-Omnigent-Runner-Id": runner_id,
                },
            ) as ap_client:
                first = await ap_client.post(
                    "/v1/runner-dispatch-receipts/transition",
                    json=transition,
                )
            assert first.status_code == 200, first.text
            assert first.json()["effects_status"] == "pending"

            drained = await app.state.replay_pending_runner_dispatch_effects()
        finally:
            runner_app_module.unregister_subagent_work(child_id)
            runner_app_module._session_inboxes_ref.pop(parent_id, None)
            await wake_client.aclose()

    source_digest = hashlib.sha256(f"{child_id}\0{key}".encode()).hexdigest()
    expected_source = f"dispatch-effects:{source_digest}"
    assert len(expected_source) <= 128
    assert len(wake_bodies) == 4
    assert {body["dispatch_source_id"] for body in wake_bodies} == {expected_source}
    assert parent_inbox.qsize() == 1
    assert len(drained) == 1
    assert drained[0]["effects_status"] == "completed"
    completed = conversations.get_runner_dispatch_receipt(
        child_id,
        idempotency_key=key,
    )
    assert completed is not None
    assert completed["effects_status"] == "completed"


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
async def test_run_service_cleans_created_root_when_initial_input_fails(
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

    created: list[str] = []
    cleaned: list[str] = []

    async def create_root(command: object, _actor_id: str) -> str:
        root = conversation_store.create_conversation(
            kind="default",
            agent_id=agent.id,
            workspace=workspace.root_path,
            agent_bundle_version=agent.version,
            agent_bundle_digest=digest,
            agent_bundle_location=agent.bundle_location,
        )
        created.append(root.id)
        return root.id

    async def reject_input(_session_id: str, _event: object, _actor_id: str) -> None:
        raise RuntimeError("input rejected")

    async def cleanup_root(session_id: str, _actor_id: str) -> None:
        cleaned.append(session_id)
        await conversation_store.delete_conversation(session_id)

    service = RunService(
        run_store=run_store,
        conversation_store=conversation_store,
        agent_store=_Agents(),
        submit_session_event=reject_input,
    )
    command = RunCreate(
        agent_id=agent.id,
        workspace_id=workspace.id,
        input="Coordinate the implementation",
        source="api:request-v1",
        source_event_id="request-input-failure",
    )

    with pytest.raises(RuntimeError, match="input rejected"):
        await service.create(
            command,
            actor_id="alice@example.com",
            auth_scope="user:alice",
            session_creator=create_root,
            session_cleaner=cleanup_root,
        )
    with pytest.raises(OmnigentError, match="previously failed"):
        await service.create(
            command,
            actor_id="alice@example.com",
            auth_scope="user:alice",
            session_creator=create_root,
            session_cleaner=cleanup_root,
        )

    assert len(created) == 1
    assert cleaned == created
    assert conversation_store.get_conversation(created[0]) is None
    assert run_store.list_runs(actor_id="alice@example.com")[0].status is RunStatus.FAILED


@pytest.mark.asyncio
async def test_session_gateway_sends_snapshot_expectation_and_cleans_late_mismatch() -> None:
    app = FastAPI()
    received: list[dict[str, object]] = []
    deleted: list[str] = []

    @app.post("/v1/sessions")
    async def create_session(payload: dict[str, object]) -> dict[str, object]:
        received.append(payload)
        return {
            "id": "1" * 32,
            "agent_bundle_version": 7,
            "agent_bundle_digest": "f" * 64,
        }

    @app.delete("/v1/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, str]:
        deleted.append(session_id)
        return {"id": session_id}

    request = Request({"type": "http", "app": app, "headers": []})
    gateway = ASGISessionGateway(request)
    digest = "a" * 64
    command = RootSessionRequest(
        agent_id="2" * 32,
        workspace="/workspace",
        host_id=None,
        execution_mode="auto",
        bundle_version=7,
        bundle_digest=digest,
        bundle_location=f"{'2' * 32}/{digest}",
    )

    with pytest.raises(OmnigentError, match="digest changed"):
        await gateway.create_root(command, "alice@example.com")

    assert received[0]["expected_agent_bundle"] == {
        "version": 7,
        "digest": digest,
        "location": f"{'2' * 32}/{digest}",
    }
    assert deleted == ["1" * 32]


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


@pytest.mark.asyncio
async def test_worktree_manager_hydrates_durable_recovery_after_restart(
    database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyRunStore(database)
    workspace = _create_workspace(store, tmp_path / "workspace")
    run = _create_run(store, workspace.id).run
    durable = store.acquire_worktree_lease(
        run_id=run.id,
        attempt_id="5" * 32,
        child_session_id="6" * 32,
        host_id="host-1",
        repository_id=workspace.repositories[0].id,
        worktree_path="/worktrees/api-recovery",
        branch="omnigent/attempt/api-recovery",
        owner_id="runner-1",
    )
    store.mark_worktree_lease_recovery_required(durable.id, owner_id="runner-1")

    removed: list[str] = []

    async def remove(**kwargs: object) -> None:
        removed.append(str(kwargs["worktree_path"]))

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    restarted = WorktreeLeaseManager(ttl_s=60, durable_store=store)

    assert len(restarted.records) == 1
    hydrated = restarted.records[0]
    assert hydrated.durable_lease_id == durable.id
    assert hydrated.run_id == run.id
    assert hydrated.attempt_id == "5" * 32
    assert hydrated.child_session_id == "6" * 32
    assert hydrated.repo_path == str((Path(workspace.root_path) / "api").resolve())
    assert hydrated.status.value == WorktreeLeaseStatus.RECOVERY_REQUIRED.value

    recovered = await restarted.recover_expired(
        host_registry=object(),
        host_conn=type("Host", (), {"host_id": "host-1"})(),
    )

    assert recovered == (hydrated,)
    assert removed == [durable.worktree_path]
    assert store.list_active_worktree_leases(run.id) == ()


@pytest.mark.asyncio
async def test_worktree_release_recovers_after_delete_before_durable_commit_crash(
    database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-absent worktree lets a fresh process finalize its lease."""
    store = SqlAlchemyRunStore(database)
    workspace = _create_workspace(store, tmp_path / "workspace")
    run = _create_run(store, workspace.id).run
    durable = store.acquire_worktree_lease(
        run_id=run.id,
        attempt_id="5" * 32,
        child_session_id="6" * 32,
        host_id="host-delete-crash",
        repository_id=workspace.repositories[0].id,
        worktree_path="/worktrees/delete-before-release",
        branch="omnigent/attempt/delete-before-release",
        owner_id="runner-delete-crash",
    )
    store.mark_worktree_lease_recovery_required(
        durable.id,
        owner_id="runner-delete-crash",
    )
    physically_present = [True]
    remove_calls = 0

    async def remove(**_kwargs: object) -> None:
        nonlocal remove_calls
        remove_calls += 1
        physically_present[0] = False

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    real_release = store.release_worktree_lease
    release_calls = 0

    def crash_once(*args: object, **kwargs: object):
        nonlocal release_calls
        release_calls += 1
        if release_calls == 1:
            raise RuntimeError("crash after host delete before durable release")
        return real_release(*args, **kwargs)

    monkeypatch.setattr(store, "release_worktree_lease", crash_once)
    first_process = WorktreeLeaseManager(ttl_s=60, durable_store=store)
    first = first_process.for_attempt("5" * 32)
    with pytest.raises(RuntimeError, match="before durable release"):
        await first_process.release(
            host_registry=object(),
            host_conn=SimpleNamespace(host_id="host-delete-crash"),
            leases=first,
            owner_id="runner-delete-crash",
        )
    assert physically_present == [False]
    assert len(store.list_active_worktree_leases(run.id)) == 1

    fresh_process = WorktreeLeaseManager(ttl_s=60, durable_store=store)
    fresh = fresh_process.for_attempt("5" * 32)
    await fresh_process.release(
        host_registry=object(),
        host_conn=SimpleNamespace(host_id="host-delete-crash"),
        leases=fresh,
        owner_id="runner-delete-crash",
    )

    assert remove_calls == 2
    assert release_calls == 2
    assert store.list_active_worktree_leases(run.id) == ()


@pytest.mark.asyncio
async def test_worktree_restart_hydrates_and_maintains_all_workspace_scopes(
    database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identical durable IDs in workspaces 0 and 7 remain tenant-isolated."""
    from omnigent.db.db_models import current_workspace_id, workspace_scope
    from omnigent.server.routes import _host_worktree
    from omnigent.stores.run_store import sqlalchemy_store as run_store_module

    run_store = SqlAlchemyRunStore(database)
    conversations = SqlAlchemyConversationStore(database)
    generated_ids = [f"{value:032x}" for value in range(1, 20)]
    next_id = [0]

    def deterministic_uuid4() -> SimpleNamespace:
        value = generated_ids[next_id[0]]
        next_id[0] += 1
        return SimpleNamespace(hex=value)

    monkeypatch.setattr(run_store_module, "uuid4", deterministic_uuid4)
    seeded: dict[int, tuple[str, str, str]] = {}
    host_id = "f" * 32
    for workspace_id in (0, 7):
        next_id[0] = 0
        with workspace_scope(workspace_id):
            workspace = _create_workspace(
                run_store,
                tmp_path / f"workspace-{workspace_id}",
            )
            run = _create_run(run_store, workspace.id).run
            root_id = run.root_session_id
            assert root_id is not None
            child_id = "e" * 32
            conversations.create_conversation(
                conversation_id=root_id,
                agent_id=run.agent_id,
                agent_bundle_version=run.bundle_version,
                agent_bundle_digest=run.bundle_digest,
                agent_bundle_location=run.bundle_location,
            )
            conversations.create_conversation(
                conversation_id=child_id,
                parent_conversation_id=root_id,
                kind="sub_agent",
                sub_agent_name="worker",
                title=f"worker: workspace {workspace_id}",
                host_id=host_id,
                workspace=f"/worktrees/workspace-{workspace_id}",
                runner_id="runner-multi-workspace",
            )
            reserved = run_store.reserve_child_dispatch(
                run_id=run.id,
                child_session_id=child_id,
                worker_name="worker",
                title="same durable ids",
                source_id="same-source",
            )
            assert reserved.attempt is not None
            lease = run_store.acquire_worktree_lease(
                run_id=run.id,
                attempt_id=reserved.attempt.id,
                child_session_id=child_id,
                host_id=host_id,
                repository_id=workspace.repositories[0].id,
                worktree_path=f"/worktrees/workspace-{workspace_id}",
                branch="omnigent/attempt/same",
                owner_id="runner-multi-workspace",
            )
            seeded[workspace_id] = (run.id, reserved.attempt.id, lease.id)

    assert seeded[0] == seeded[7]
    restarted = WorktreeLeaseManager(
        ttl_s=60,
        startup_grace_s=30,
        durable_store=run_store,
    )
    assert {lease.workspace_id for lease in restarted.records} == {0, 7}
    shared_attempt_id = seeded[0][1]
    for workspace_id in (0, 7):
        with workspace_scope(workspace_id):
            leases = restarted.for_attempt(shared_attempt_id)
            assert len(leases) == 1
            assert leases[0].workspace_id == workspace_id
            assert leases[0].repo_path.startswith(
                str((tmp_path / f"workspace-{workspace_id}").resolve())
            )
            child = conversations.get_conversation("e" * 32)
            assert child is not None
            assert child.title == f"worker: workspace {workspace_id}"

    monkeypatch.setattr(_host_worktree, "_attempt_worktree_lease_manager", restarted)
    observed_scopes: list[int] = []
    stop = asyncio.Event()

    def liveness(_child_ids: list[str]) -> dict[str, object]:
        observed_scopes.append(current_workspace_id())
        if set(observed_scopes) == {0, 7}:
            stop.set()
        return {}

    await _host_worktree.maintain_attempt_worktree_leases(
        SimpleNamespace(get=lambda _host_id: None),
        stop,
        conversation_store=conversations,
        liveness_lookup=liveness,
        interval_s=0.01,
    )

    assert set(observed_scopes) == {0, 7}
    assert current_workspace_id() == 0


@pytest.mark.asyncio
async def test_fresh_maintenance_deletes_initial_child_after_release_finalize_crash(
    database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A durable claim completes even when its lease-owning worker already died."""
    from omnigent.server.routes import _host_worktree

    run_store = SqlAlchemyRunStore(database)
    conversations = SqlAlchemyConversationStore(database)
    workspace = _create_workspace(run_store, tmp_path / "workspace")
    run = _create_run(run_store, workspace.id).run
    root_id = run.root_session_id
    assert root_id is not None
    conversations.create_conversation(
        conversation_id=root_id,
        agent_id=run.agent_id,
        agent_bundle_version=run.bundle_version,
        agent_bundle_digest=run.bundle_digest,
        agent_bundle_location=run.bundle_location,
    )
    child_id = "2" * 32
    host_id = "3" * 32
    runner_id = "runner-release-crash"
    child = conversations.create_conversation(
        conversation_id=child_id,
        parent_conversation_id=root_id,
        kind="sub_agent",
        sub_agent_name="worker",
        title="worker: release crash",
        host_id=host_id,
        workspace="/worktrees/release-crash",
        runner_id=runner_id,
    )
    reserved = run_store.reserve_child_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        worker_name="worker",
        title="release crash",
        source_id="release-crash",
    )
    assert reserved.attempt is not None
    attempt_id = reserved.attempt.id
    durable = run_store.acquire_worktree_lease(
        run_id=run.id,
        attempt_id=attempt_id,
        child_session_id=child_id,
        host_id=host_id,
        repository_id=workspace.repositories[0].id,
        worktree_path=child.workspace,
        branch="omnigent/attempt/release-crash",
        owner_id=runner_id,
    )
    run_store.mark_worktree_lease_recovery_required(
        durable.id,
        owner_id=runner_id,
    )
    assert conversations.claim_host_runner_recovery(
        child_id,
        attempt_id=attempt_id,
        expected_runner_id=runner_id,
        expected_workspace=child.workspace,
        host_id=host_id,
    )

    removed: list[str] = []

    async def _remove(**kwargs: object) -> None:
        removed.append(str(kwargs["worktree_path"]))

    monkeypatch.setattr(
        "omnigent.workspaces.worktree_lease.remove_worktree_on_host",
        _remove,
    )
    releasing_worker = WorktreeLeaseManager(ttl_s=60, durable_store=run_store)
    leases = releasing_worker.for_attempt(attempt_id)
    assert len(leases) == 1
    await releasing_worker.release(
        host_registry=object(),
        host_conn=SimpleNamespace(host_id=host_id),
        leases=leases,
        owner_id=runner_id,
    )
    assert removed == [child.workspace]
    assert run_store.list_active_worktree_leases(run.id) == ()
    assert conversations.list_host_runner_recovery_claims()[0]["attempt_id"] == attempt_id

    # Crash boundary: the releasing worker never calls
    # _finalize_recovered_attempt_bindings. A new process hydrates no leases
    # and must discover the claim independently from ConversationStore.
    fresh_manager = WorktreeLeaseManager(ttl_s=60, durable_store=run_store)
    assert fresh_manager.for_attempt(attempt_id) == ()
    monkeypatch.setattr(
        _host_worktree,
        "_attempt_worktree_lease_manager",
        fresh_manager,
    )
    stop = asyncio.Event()
    maintenance = asyncio.create_task(
        _host_worktree.maintain_attempt_worktree_leases(
            SimpleNamespace(get=lambda _host_id: None),
            stop,
            conversation_store=conversations,
            interval_s=0.01,
        )
    )
    try:
        async with asyncio.timeout(2):
            while conversations.get_conversation(child_id) is not None:
                await asyncio.sleep(0.01)
    finally:
        stop.set()
        await maintenance

    assert conversations.get_conversation(child_id) is None
    assert conversations.list_host_runner_recovery_claims() == []


@pytest.mark.asyncio
async def test_worktree_manager_restores_heartbeat_for_live_active_attempt_after_restart(
    database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified live Attempt survives AP restart and renews its durable lease."""
    store = SqlAlchemyRunStore(database)
    workspace = _create_workspace(store, tmp_path / "workspace")
    run = _create_run(store, workspace.id).run
    child_id = "6" * 32
    host_id = "8" * 32
    reservation = store.reserve_child_dispatch(
        run_id=run.id,
        child_session_id=child_id,
        worker_name="worker",
        title="live task",
        source_id="restart-live-attempt",
    )
    assert reservation.attempt is not None
    attempt_id = reservation.attempt.id
    store.apply_projection_event(
        ProjectionEvent(
            source="session-runtime",
            source_event_id=f"dispatch:{child_id}:{'7' * 32}",
            event_type="dispatch.created",
            run_id=run.id,
            session_id=child_id,
            conversation_item_id="7" * 32,
            payload={
                "child_session_id": child_id,
                "worker_name": "worker",
                "title": "live task",
                "dispatch_call_id": "7" * 32,
            },
        )
    )
    conversations = SqlAlchemyConversationStore(database)
    conversations.create_conversation(
        agent_id="a" * 32,
        conversation_id=run.root_session_id,
        agent_bundle_version=run.bundle_version,
        agent_bundle_digest=run.bundle_digest,
        agent_bundle_location=run.bundle_location,
    )
    conversations.create_conversation(
        agent_id="a" * 32,
        conversation_id=child_id,
        parent_conversation_id=run.root_session_id,
        kind="sub_agent",
        sub_agent_name="worker",
        host_id=host_id,
        runner_id="runner-1",
        workspace=str(tmp_path / "attempt"),
        agent_bundle_version=run.bundle_version,
        agent_bundle_digest=run.bundle_digest,
        agent_bundle_location=run.bundle_location,
    )
    store.acquire_worktree_lease(
        run_id=run.id,
        attempt_id=attempt_id,
        child_session_id=child_id,
        host_id=host_id,
        repository_id=workspace.repositories[0].id,
        worktree_path="/worktrees/api-live",
        branch="omnigent/attempt/api-live",
        owner_id="runner-1",
    )
    removed: list[str] = []

    async def remove(**kwargs: object) -> None:
        removed.append(str(kwargs["worktree_path"]))

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    now = [100.0]
    restarted = WorktreeLeaseManager(
        ttl_s=60,
        startup_grace_s=10,
        clock=lambda: now[0],
        durable_store=store,
    )
    host_conn = SimpleNamespace(host_id=host_id)
    empty_registry = SimpleNamespace(get=lambda _candidate: None)
    connected_registry = SimpleNamespace(
        get=lambda candidate: host_conn if candidate == host_id else None
    )

    await restarted.reconcile_hydrated_active(
        host_registry=empty_registry,
        conversation_store=conversations,
        liveness_lookup=lambda _ids: {},
    )
    assert {lease.status for lease in restarted.for_attempt(attempt_id)} == {
        LeaseStatus.ACTIVE
    }

    now[0] = 105.0
    await restarted.reconcile_hydrated_active(
        host_registry=connected_registry,
        conversation_store=conversations,
        liveness_lookup=lambda ids: {
            child_id: SimpleNamespace(runner_online=True, host_online=True)
        },
    )
    recovered = await restarted.recover_expired(
        host_registry=connected_registry,
        host_conn=host_conn,
    )
    await restarted.stop_heartbeat(restarted.for_attempt(attempt_id))

    assert recovered == ()
    assert removed == []
    assert {lease.status for lease in restarted.for_attempt(attempt_id)} == {
        LeaseStatus.ACTIVE
    }

    expired_clock = [200.0]
    expired = WorktreeLeaseManager(
        ttl_s=60,
        startup_grace_s=10,
        clock=lambda: expired_clock[0],
        durable_store=store,
    )
    await expired.reconcile_hydrated_active(
        host_registry=empty_registry,
        conversation_store=conversations,
        liveness_lookup=lambda _ids: {},
    )
    expired_clock[0] = 211.0
    await expired.reconcile_hydrated_active(
        host_registry=empty_registry,
        conversation_store=conversations,
        liveness_lookup=lambda _ids: {},
    )
    assert {lease.status for lease in expired.for_attempt(attempt_id)} == {
        LeaseStatus.RECOVERY_REQUIRED
    }
    recovered = await expired.recover_expired(
        host_registry=connected_registry,
        host_conn=host_conn,
    )
    assert len(recovered) == 1
    assert removed == ["/worktrees/api-live"]
