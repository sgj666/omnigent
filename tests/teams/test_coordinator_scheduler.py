"""Coordinator, DAG scheduling, and Parent Inbox contracts."""

from __future__ import annotations

import pytest

from omnigent.entities.run import Task, TaskStatus
from omnigent.entities.team import AgentProfile, AgentRole
from omnigent.teams.coordinator import Coordinator
from omnigent.teams.router import CoordinatorRouter, ParentInbox
from omnigent.teams.scheduler import DAGScheduler


def _coordinator() -> Coordinator:
    return Coordinator(
        profiles=[
            AgentProfile("backend", "Backend", AgentRole.WORKER, ["code"]),
            AgentProfile("reviewer", "Reviewer", AgentRole.WORKER, ["review"]),
        ],
        stage_profiles={"implementation": "backend", "review": "reviewer"},
        team_concurrency=4,
    )


def test_completed_worker_unblocks_review_without_human_comment() -> None:
    coordinator = _coordinator()
    coordinator.add_task(Task("task-1", "run-1", "implementation"))
    coordinator.add_task(Task("review-task", "run-1", "review"), stage="review")
    coordinator.scheduler.add_dependency("review-task", "task-1")

    attempts = coordinator.start_run("run-1")
    assert len(attempts) == 1
    coordinator.on_worker_completed("run-1", "task-1", attempts[0].id)

    assert coordinator.task("review-task").status is TaskStatus.RUNNING
    assert coordinator.scheduler.attempts[next(iter(
        attempt.id for attempt in coordinator.scheduler.active_attempts()
        if attempt.task_id == "review-task"
    ))].agent_profile_id == "reviewer"
    assert coordinator.wake_count("run-1") == 1


def test_same_issue_can_use_different_profiles_by_stage() -> None:
    coordinator = _coordinator()
    assert coordinator.choose_profile(stage="implementation").id == "backend"  # type: ignore[union-attr]
    assert coordinator.choose_profile(stage="review").id == "reviewer"  # type: ignore[union-attr]


def test_independent_tasks_run_in_parallel_and_respect_team_limit() -> None:
    coordinator = _coordinator()
    coordinator.scheduler.team_concurrency = 2
    for task_id in ("a", "b", "c"):
        coordinator.add_task(Task(task_id, "run-1", task_id))
    attempts = coordinator.start_run("run-1")
    assert len(attempts) == 2


def test_task_waits_when_no_profile_has_required_capability() -> None:
    coordinator = _coordinator()
    coordinator.add_task(
        Task("task-1", "run-1", "implementation"),
        required_capabilities=("security",),
    )

    assert coordinator.start_run("run-1") == ()
    assert coordinator.task("task-1").status is TaskStatus.PENDING


def test_scheduler_rechecks_capabilities_for_explicit_profile_and_selector() -> None:
    profile = AgentProfile("worker", "Worker", AgentRole.WORKER, ["code"])
    for scheduler in (
        DAGScheduler([profile]),
        DAGScheduler([profile], profile_selector=lambda _stage, _caps: profile),
    ):
        scheduler.add_task(
            Task(f"task-{id(scheduler)}", "run-1", "task"),
            required_capabilities=("security",),
            profile_id="worker" if scheduler.profile_selector is None else None,
        )
        assert scheduler.schedule() == ()


def test_failure_retries_then_hard_blocks_with_diagnostics() -> None:
    coordinator = _coordinator()
    coordinator.add_task(Task("task-1", "run-1", "implementation"), max_retries=1)
    attempt = coordinator.start_run("run-1")[0]
    first = coordinator.on_attempt_failed(
        "run-1",
        "task-1",
        attempt.id,
        failure_code="TEST_COMMAND_EXIT_1",
        exit_code=1,
        last_tool_call="pytest",
        log_ref="logs/attempt-1",
        suggested_action="retry",
    )
    assert first.hard_block is False
    retry = next(
        attempt
        for attempt in coordinator.scheduler.active_attempts()
        if attempt.task_id == "task-1"
    )
    second = coordinator.on_attempt_failed(
        "run-1",
        "task-1",
        retry.id,
        failure_code="TEST_COMMAND_EXIT_1",
        exit_code=1,
        last_tool_call="pytest",
        log_ref="logs/attempt-2",
        suggested_action="fix test failure",
    )
    assert second.hard_block is True
    assert second.retry_count == 2
    assert coordinator.task("task-1").status is TaskStatus.FAILED


def test_parent_inbox_duplicate_completion_wakes_once() -> None:
    coordinator = _coordinator()
    coordinator.add_task(Task("task-1", "run-1", "implementation"))
    attempt = coordinator.start_run("run-1")[0]
    router = CoordinatorRouter(coordinator)
    assert router.route_worker_completed("run-1", "task-1", attempt.id, event_id="evt-1")
    assert not router.route_worker_completed("run-1", "task-1", attempt.id, event_id="evt-1")
    assert coordinator.wake_count("run-1") == 1


def test_cross_run_and_terminal_completion_is_rejected() -> None:
    coordinator = _coordinator()
    coordinator.add_task(Task("task-1", "run-1", "implementation"))
    attempt = coordinator.start_run("run-1")[0]
    with pytest.raises(ValueError, match="run"):
        coordinator.on_worker_completed("run-2", "task-1", attempt.id)
    coordinator.on_worker_completed("run-1", "task-1", attempt.id)
    coordinator.on_worker_completed("run-1", "task-1", attempt.id)


class _FailureLedger:
    def __init__(self) -> None:
        self.failures: list[tuple[str, object]] = []

    def record_failure(self, run_id: str, failure: object) -> None:
        self.failures.append((run_id, failure))


def test_failure_is_recorded_in_injected_ledger() -> None:
    ledger = _FailureLedger()
    coordinator = Coordinator(
        profiles=[AgentProfile("backend", "Backend", AgentRole.WORKER, ["code"])],
        ledger=ledger,
    )
    coordinator.add_task(Task("task-1", "run-1", "implementation"))
    attempt = coordinator.start_run("run-1")[0]
    coordinator.on_attempt_failed(
        "run-1", "task-1", attempt.id, failure_code="EXIT", exit_code=1
    )
    assert len(ledger.failures) == 1
    assert ledger.failures[0][1].failure_code == "EXIT"  # type: ignore[union-attr]
    repeated = coordinator.on_attempt_failed(
        "run-1", "task-1", attempt.id, failure_code="EXIT", exit_code=1
    )
    assert repeated == ledger.failures[0][1]
    assert len(coordinator.failure_events) == 1
    assert len(ledger.failures) == 1


def test_inbox_can_buffer_before_coordinator_is_attached() -> None:
    inbox = ParentInbox()
    assert inbox.put(run_id="run-1", task_id="task-1", attempt_id="attempt-1")
    assert len(inbox) == 1
