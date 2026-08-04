from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import pytest

from omnigent.entities.run_projection import (
    Attempt,
    AttemptStatus,
    InspectorFailure,
    InspectorRun,
    ProjectionEvent,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)


def _evaluation() -> Any:
    try:
        return importlib.import_module("omnigent.evaluation.service")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Session-backed evaluation service is missing: {exc}")


def _inspector(*, status: RunStatus = RunStatus.COMPLETED) -> InspectorRun:
    run = Run(
        id="1" * 32,
        actor_id="alice",
        auth_scope="user:alice",
        source="api",
        source_event_id="source-1",
        agent_id="2" * 32,
        bundle_version=1,
        bundle_digest="3" * 64,
        bundle_location=f"{'2' * 32}/{'3' * 64}",
        workspace_id="4" * 32,
        root_session_id="5" * 32,
        status=status,
        created_at=1,
        updated_at=50,
    )
    tasks = (
        Task(
            id="6" * 32,
            run_id=run.id,
            title="API",
            status=TaskStatus.COMPLETED,
            child_session_id="8" * 32,
            created_at=10,
            updated_at=30,
        ),
        Task(
            id="7" * 32,
            run_id=run.id,
            title="Web",
            status=TaskStatus.FAILED,
            child_session_id="9" * 32,
            created_at=20,
            updated_at=40,
        ),
    )
    attempts = (
        Attempt(
            id="a" * 32,
            task_id=tasks[0].id,
            status=AttemptStatus.SUCCEEDED,
            child_session_id=tasks[0].child_session_id,
            worker_name="api-worker",
            started_at=10,
            completed_at=30,
            created_at=10,
            updated_at=30,
        ),
        Attempt(
            id="b" * 32,
            task_id=tasks[1].id,
            status=AttemptStatus.FAILED,
            child_session_id=tasks[1].child_session_id,
            worker_name="web-worker",
            started_at=20,
            completed_at=40,
            failure_code="tests_failed",
            failure_message="unit tests failed",
            created_at=20,
            updated_at=40,
        ),
        Attempt(
            id="c" * 32,
            task_id=tasks[0].id,
            status=AttemptStatus.BLOCKED,
            child_session_id=tasks[0].child_session_id,
            worker_name="api-worker",
            started_at=32,
            failure_code="approval_blocked",
            failure_message="waiting for approval",
            created_at=32,
            updated_at=38,
        ),
    )
    return InspectorRun(
        run=run,
        root_session_id=run.root_session_id,
        child_session_ids=("8" * 32, "9" * 32),
        conversation_item_ids=("d" * 32, "e" * 32),
        tasks=tasks,
        attempts=attempts,
        failures=(
            InspectorFailure(
                attempt_id=attempts[1].id,
                code="tests_failed",
                message="unit tests failed",
            ),
            InspectorFailure(
                attempt_id=attempts[2].id,
                code="approval_blocked",
                message="waiting for approval",
            ),
        ),
    )


def _event(
    event_type: str,
    source_event_id: str,
    occurred_at: int,
    *,
    session_id: str | None = None,
    attempt_id: str | None = None,
    conversation_item_id: str | None = None,
    **payload: Any,
) -> ProjectionEvent:
    return ProjectionEvent(
        source="session-runtime",
        source_event_id=source_event_id,
        event_type=event_type,
        run_id="1" * 32,
        session_id=session_id,
        attempt_id=attempt_id,
        conversation_item_id=conversation_item_id,
        payload={"occurred_at": occurred_at, **payload},
    )


def _events() -> tuple[ProjectionEvent, ...]:
    return (
        _event(
            "session.blocked",
            "blocked-1",
            33,
            session_id="8" * 32,
            attempt_id="c" * 32,
        ),
        _event(
            "session.running",
            "resumed-1",
            36,
            session_id="8" * 32,
            attempt_id="c" * 32,
        ),
        _event(
            "parent_inbox.relayed",
            "relay-1",
            41,
            session_id="9" * 32,
            attempt_id="b" * 32,
            conversation_item_id="f" * 32,
        ),
        _event(
            "coordinator.activity",
            "root-activity-1",
            46,
            session_id="5" * 32,
            conversation_item_id="0" * 32,
        ),
        _event(
            "worktree.created",
            "worktree-1",
            10,
            attempt_id="a" * 32,
            worktree_path="/tmp/worktree",
        ),
        _event(
            "worktree.released",
            "commit-1",
            30,
            attempt_id="a" * 32,
            output_commit="abc123",
        ),
        _event("artifact.created", "artifact-1", 31, attempt_id="a" * 32),
        _event("test.completed", "test-1", 32, attempt_id="a" * 32),
    )


class _Runs:
    def __init__(self, inspector: InspectorRun, events: tuple[ProjectionEvent, ...]) -> None:
        self.inspector = inspector
        self.events = events

    def inspect_run(self, run_id: str) -> InspectorRun:
        if run_id != self.inspector.run.id:
            raise ValueError("Run not found")
        return self.inspector

    def list_projection_events(self, run_id: str) -> tuple[ProjectionEvent, ...]:
        assert run_id == self.inspector.run.id
        return self.events


def test_metrics_cover_completion_parallel_retry_blocked_latency_and_evidence() -> None:
    module = _evaluation()
    service = module.RunEvaluationService(_Runs(_inspector(), _events()), clock=lambda: 100)

    record = service.evaluate("1" * 32, owner_user_id="alice")

    assert record.status.value == "final"
    assert record.metrics.task_completion_rate == 0.5
    assert record.metrics.attempt_success_rate == pytest.approx(1 / 3)
    assert record.metrics.retry_count == 1
    assert record.metrics.blocked_count == 1
    assert record.metrics.blocked_duration_seconds == 3
    assert record.metrics.parallel_overlap_seconds == 10
    assert record.metrics.max_concurrency == 2
    assert record.metrics.worker_duration_seconds == 46
    assert record.metrics.parent_inbox_latency_seconds == 5
    assert record.metrics.parent_inbox_latency_samples == 1
    assert record.metrics.failure_categories == {"blocked": 1, "test": 1}
    assert record.metrics.evidence_counts.worktree == 2
    assert record.metrics.evidence_counts.commit == 1
    assert record.metrics.evidence_counts.artifact == 1
    assert record.metrics.evidence_counts.test == 1
    assert record.metrics.evidence_counts.session == 3
    assert record.metrics.evidence_counts.conversation_item == 4
    assert {worker.worker_name for worker in record.workers} == {"api-worker", "web-worker"}
    api = next(worker for worker in record.workers if worker.worker_name == "api-worker")
    assert (api.attempt_count, api.retry_count, api.blocked_count) == (2, 1, 1)


def test_running_run_is_preview_and_rubric_is_opt_in() -> None:
    module = _evaluation()
    calls: list[str] = []

    def rubric(inspector: InspectorRun, _metrics: Any) -> dict[str, Any]:
        calls.append(inspector.run.id)
        return {"score": 0.75}

    preview = replace(_inspector(), run=replace(_inspector().run, status=RunStatus.RUNNING))
    default = module.RunEvaluationService(_Runs(preview, ()), clock=lambda: 100)
    opted_in = module.RunEvaluationService(
        _Runs(preview, ()), rubric_evaluator=rubric, clock=lambda: 100
    )

    default_record = default.evaluate(preview.run.id, owner_user_id="alice")
    rubric_record = opted_in.evaluate(preview.run.id, owner_user_id="alice")

    assert default_record.status.value == "preview"
    assert default_record.rubric is None
    assert calls == [preview.run.id]
    assert rubric_record.rubric == {"score": 0.75}


def test_evaluator_is_idempotent_and_never_controls_agents() -> None:
    module = _evaluation()

    class Records:
        def __init__(self) -> None:
            self.record = None
            self.upserts = 0

        def get(self, **_kwargs: Any) -> Any:
            return self.record

        def upsert(self, record: Any) -> Any:
            self.upserts += 1
            self.record = record
            return record

    records = Records()
    service = module.RunEvaluationService(
        _Runs(_inspector(), _events()), evaluation_store=records, clock=lambda: 100
    )

    first = service.evaluate("1" * 32, owner_user_id="alice")
    second = service.evaluate("1" * 32, owner_user_id="alice")
    refreshed = service.evaluate("1" * 32, owner_user_id="alice", refresh=True)

    assert second == first
    assert refreshed.id == first.id
    assert records.upserts == 2
    assert not any(
        word in module.__dict__ or word in vars(service)
        for word in ("start_agent", "retry_agent", "wake_agent")
    )


def test_wrong_owner_and_unknown_run_are_indistinguishable() -> None:
    module = _evaluation()
    service = module.RunEvaluationService(_Runs(_inspector(), ()))

    for run_id, owner in (("1" * 32, "mallory"), ("f" * 32, "alice")):
        with pytest.raises(Exception) as raised:
            service.evaluate(run_id, owner_user_id=owner)
        assert getattr(raised.value, "code", None) == "not_found"
