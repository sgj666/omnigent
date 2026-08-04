from __future__ import annotations

import logging
from pathlib import Path

from omnigent.db.db_models import OmnigentBase
from omnigent.db.utils import get_or_create_engine
from omnigent.entities.run_projection import AttemptStatus, RunStatus, TaskStatus
from omnigent.runs.session_projection import SessionRunProjection
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore


def _runtime(tmp_path: Path):
    database = f"sqlite:///{tmp_path / 'session-projection.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    runs = SqlAlchemyRunStore(database)
    conversations = SqlAlchemyConversationStore(database)
    workspace = runs.create_workspace(root_path=str(tmp_path), repositories=())
    created = runs.create_run_idempotent(
        auth_scope="user:alice",
        actor_id="alice@example.com",
        source="api.request-v1",
        source_event_id="request-1",
        agent_id="a" * 32,
        bundle_version=3,
        bundle_digest="b" * 64,
        bundle_location=f"{'a' * 32}/{'b' * 64}",
        workspace_id=workspace.id,
        root_session_id="c" * 32,
    )
    root = conversations.create_conversation(
        conversation_id=created.run.root_session_id,
        kind="default",
        title="Coordinator",
        agent_id=created.run.agent_id,
        workspace=workspace.root_path,
        agent_bundle_version=created.run.bundle_version,
        agent_bundle_digest=created.run.bundle_digest,
        agent_bundle_location=created.run.bundle_location,
    )
    return runs, conversations, created.run, root


def test_session_backed_projection_tracks_parallel_children_retries_and_relay(
    tmp_path: Path,
) -> None:
    runs, conversations, run, root = _runtime(tmp_path)
    projection = SessionRunProjection(runs)
    projection.root_created(run)
    api_child = conversations.create_conversation(
        kind="sub_agent",
        title="coder:API implementation",
        parent_conversation_id=root.id,
        agent_id=run.agent_id,
        sub_agent_name="coder",
    )
    web_child = conversations.create_conversation(
        kind="sub_agent",
        title="coder:Web implementation",
        parent_conversation_id=root.id,
        agent_id=run.agent_id,
        sub_agent_name="coder",
    )
    projection.child_created(api_child)
    projection.child_created(web_child)

    api_dispatch = projection.dispatch_accepted(api_child, conversation_item_id="1" * 32)
    web_dispatch = projection.dispatch_accepted(web_child, conversation_item_id="2" * 32)

    tasks = runs.list_tasks(run.id)
    attempts = runs.list_attempts(run.id)
    assert len(tasks) == 2
    assert len(attempts) == 2
    assert {task.title for task in tasks} == {"API implementation", "Web implementation"}
    assert {attempt.status for attempt in attempts} == {AttemptStatus.RUNNING}
    assert {attempt.child_session_id for attempt in attempts} == {api_child.id, web_child.id}

    projection.terminal(
        api_child,
        status="completed",
        response_id="response-api-1",
        conversation_item_id="3" * 32,
    )
    projection.terminal(
        web_child,
        status="failed",
        response_id="response-web-1",
        conversation_item_id="4" * 32,
        failure_code="worker_failed",
        failure_message="tests failed",
    )
    projection.parent_inbox_relayed(
        web_child,
        status="failed",
        conversation_item_id="5" * 32,
    )

    retry = projection.dispatch_accepted(api_child, conversation_item_id="6" * 32)
    projection.blocked(
        api_child,
        block_id="approval-1",
        reason="Awaiting database migration approval",
    )
    projection.parent_inbox_relayed(
        api_child,
        status="blocked",
        conversation_item_id="7" * 32,
    )

    assert api_dispatch is not None and api_dispatch.attempt is not None
    assert web_dispatch is not None and web_dispatch.attempt is not None
    assert retry is not None and retry.attempt is not None
    assert retry.task is not None and retry.task.id == api_dispatch.task.id
    assert retry.attempt.id != api_dispatch.attempt.id
    assert len(runs.list_tasks(run.id)) == 2
    assert len(runs.list_attempts(run.id)) == 3
    tasks_by_title = {task.title: task for task in runs.list_tasks(run.id)}
    assert tasks_by_title["API implementation"].status is TaskStatus.BLOCKED
    assert runs.get_run(run.id).status is RunStatus.RUNNING

    projection.dependency(
        run,
        task_id=web_dispatch.task.id,
        depends_on_task_id=api_dispatch.task.id,
        source_event_id="dependency-1",
    )
    projection.dependency(
        run,
        task_id=web_dispatch.task.id,
        depends_on_task_id=api_dispatch.task.id,
        source_event_id="dependency-1",
    )
    assert runs.list_dependencies(run.id) == ((web_dispatch.task.id, api_dispatch.task.id),)

    # Replaying the already accepted child input cannot mint a fourth Attempt.
    replay = projection.dispatch_accepted(api_child, conversation_item_id="6" * 32)
    assert replay is not None and replay.created is False
    assert len(runs.list_attempts(run.id)) == 3

    inspector = runs.inspect_run(run.id)
    assert inspector.root_session_id == root.id
    assert set(inspector.child_session_ids) == {api_child.id, web_child.id}
    assert {failure.message for failure in inspector.failures} == {
        "tests failed",
        "Awaiting database migration approval",
    }
    assert any(
        event.event_type == "parent_inbox.relayed" for event in runs.list_projection_events(run.id)
    )

    # The Run remains pinned even if the mutable Agent would later move on.
    persisted = runs.get_run(run.id)
    assert persisted is not None
    assert (persisted.bundle_version, persisted.bundle_digest, persisted.workspace_id) == (
        3,
        "b" * 64,
        run.workspace_id,
    )


def test_projection_failure_is_logged_and_never_escapes(caplog) -> None:
    class _BrokenStore:
        def apply_projection_event(self, event):
            raise RuntimeError("projection unavailable")

    projection = SessionRunProjection(_BrokenStore())
    fake_run = type("Run", (), {"id": "run-1", "root_session_id": "root-1"})()

    with caplog.at_level(logging.ERROR, logger="omnigent.runs.session_projection"):
        assert projection.root_created(fake_run) is None

    assert "projection unavailable" in caplog.text
