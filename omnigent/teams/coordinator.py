"""Coordinator orchestration for team runs.

The coordinator is the single entry point for worker results.  It keeps the
model-facing part intentionally small: plans are represented by validated
``Task`` values and all progression is deterministic in :class:`DAGScheduler`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from time import monotonic_ns

from omnigent.entities.run import RunStatus, Task
from omnigent.entities.team import AgentProfile
from omnigent.teams.events import ActorType, EventType, LedgerEvent
from omnigent.teams.scheduler import AttemptFailed, DAGScheduler, TaskSpec
from omnigent.teams.states import RunState


class CoordinatorLedger:
    """Minimal in-memory task view used when no durable ledger is injected."""

    def __init__(self, scheduler: DAGScheduler) -> None:
        self._scheduler = scheduler
        self.failures: list[tuple[str, AttemptFailed]] = []

    def task(self, task_id: str) -> Task:
        return self._scheduler.tasks[task_id].task

    def tasks(self) -> tuple[Task, ...]:
        return tuple(spec.task for spec in self._scheduler.tasks.values())

    def record_failure(self, run_id: str, failure: AttemptFailed) -> None:
        self.failures.append((run_id, failure))


@dataclass(frozen=True)
class CoordinatorWake:
    run_id: str
    task_id: str
    attempt_id: str


class Coordinator:
    """Fixed run coordinator with stage-aware worker profile selection."""

    def __init__(
        self,
        team: object | None = None,
        profiles: Iterable[AgentProfile] | Mapping[str, AgentProfile] = (),
        *,
        scheduler: DAGScheduler | None = None,
        ledger: object | None = None,
        stage_profiles: Mapping[str, str | AgentProfile] | None = None,
        team_concurrency: int | None = None,
        profile_concurrency: Mapping[str, int] | None = None,
        lease_acquirer: object | None = None,
    ) -> None:
        del team  # Team identity is carried by the run in this pure coordinator.
        if isinstance(profiles, Mapping):
            profile_values = tuple(profiles.values())
            self.profiles = dict(profiles)
        else:
            profile_values = tuple(profiles)
            self.profiles = {profile.id: profile for profile in profile_values}
        self.stage_profiles = dict(stage_profiles or {})
        self.scheduler = scheduler or DAGScheduler(
            profile_values,
            team_concurrency=team_concurrency,
            profile_concurrency=profile_concurrency,
            profile_selector=self._select_for_scheduler,
            lease_acquirer=lease_acquirer if callable(lease_acquirer) else None,
        )
        # A supplied scheduler may not have the coordinator's selector yet.
        self.scheduler.profiles.update(self.profiles)
        self.scheduler.profile_selector = self._select_for_scheduler
        self.ledger = ledger or CoordinatorLedger(self.scheduler)
        self._run_states: dict[str, RunState] = {}
        self._wake_keys: set[tuple[str, str]] = set()
        self._wake_counts: dict[str, int] = {}
        self.failure_events: list[AttemptFailed] = []

    def add_task(
        self,
        task: Task,
        *,
        stage: str = "implementation",
        required_capabilities: Iterable[str] = (),
        profile_id: str | None = None,
        max_retries: int = 0,
    ) -> TaskSpec:
        spec = self.scheduler.add_task(
            task,
            stage=stage,
            required_capabilities=required_capabilities,
            profile_id=profile_id,
            max_retries=max_retries,
        )
        add = getattr(self.ledger, "add_task", None)
        if callable(add):
            add(task)
        return spec

    def start_run(self, run_id: str) -> tuple[object, ...]:
        """Start a run and immediately dispatch all independent ready tasks."""

        state = self._run_states.get(run_id, RunState.queued(run_id))
        if state.status is RunStatus.QUEUED:
            event = LedgerEvent(
                event_id=f"run-started:{run_id}",
                run_id=run_id,
                event_type=EventType.RUN_STARTED,
                actor_type=ActorType.COORDINATOR,
                actor_id="coordinator",
                occurred_at=monotonic_ns(),
                payload={},
                correlation_id=None,
            )
            self._append_event(run_id, event)
            self._run_states[run_id] = RunState.running(run_id)
        return tuple(self.scheduler.schedule(run_id))

    def choose_profile(
        self, stage: str, required_capabilities: Iterable[str] = ()
    ) -> AgentProfile | None:
        """Choose a profile for a stage, allowing one issue to change profiles."""

        required = set(required_capabilities)
        selected = self.stage_profiles.get(stage)
        if isinstance(selected, AgentProfile):
            return selected if required.issubset(selected.capabilities) else None
        if isinstance(selected, str):
            profile = self.profiles.get(selected)
            if profile is not None and required.issubset(profile.capabilities):
                return profile
            return None
        candidates = tuple(
            profile
            for profile in self.profiles.values()
            if required.issubset(profile.capabilities)
        )
        if candidates:
            if stage == "review":
                reviewer = next(
                    (
                        profile
                        for profile in candidates
                        if "review" in f"{profile.id} {profile.name}".lower()
                    ),
                    None,
                )
                if reviewer is not None:
                    return reviewer
            if stage == "implementation":
                backend = next(
                    (
                        profile
                        for profile in candidates
                        if "backend" in f"{profile.id} {profile.name}".lower()
                    ),
                    None,
                )
                if backend is not None:
                    return backend
            return candidates[0]
        return None

    def on_worker_completed(
        self, run_id: str, task_id: str, attempt_id: str
    ) -> tuple[object, ...]:
        """Consume a Parent Inbox completion and wake the coordinator once."""

        spec = self.scheduler.tasks.get(task_id)
        if spec is None or spec.task.run_id != run_id:
            raise ValueError("task does not belong to run")
        attempt = self.scheduler.attempts.get(attempt_id)
        if attempt is None or attempt.task_id != task_id:
            raise ValueError("attempt does not belong to task")
        key = (run_id, attempt_id)
        if key in self._wake_keys:
            return ()
        state = self._run_states.get(run_id)
        if state is None or state.status is not RunStatus.RUNNING:
            raise ValueError(f"run {run_id!r} is not running")
        changed = self.scheduler.complete(task_id, attempt_id)
        if not changed:
            return ()
        self._wake_keys.add(key)
        self._wake_counts[run_id] = self._wake_counts.get(run_id, 0) + 1
        event = LedgerEvent(
            event_id=f"worker-completed:{attempt_id}",
            run_id=run_id,
            event_type=EventType.WORKER_COMPLETED,
            actor_type=ActorType.WORKER,
            actor_id=self.scheduler.attempts[attempt_id].agent_profile_id,
            occurred_at=monotonic_ns(),
            payload={"task_id": task_id, "attempt_id": attempt_id},
            correlation_id=attempt_id,
        )
        self._append_event(run_id, event)
        self._refresh_run_status(run_id)
        return tuple(self.scheduler.schedule(run_id))

    def on_attempt_failed(
        self, run_id: str, task_id: str, attempt_id: str, **details: object
    ) -> AttemptFailed:
        state = self._run_states.get(run_id)
        if state is None or state.status is not RunStatus.RUNNING:
            raise ValueError(f"run {run_id!r} is not running")
        spec = self.scheduler.tasks.get(task_id)
        attempt = self.scheduler.attempts.get(attempt_id)
        if spec is None or spec.task.run_id != run_id:
            raise ValueError("task does not belong to run")
        if attempt is None or attempt.task_id != task_id:
            raise ValueError("attempt does not belong to task")
        failure = self.scheduler.fail(task_id, attempt_id, **details)  # type: ignore[arg-type]
        self.failure_events.append(failure)
        self._record_failure(run_id, failure)
        if failure.hard_block:
            self._run_states[run_id] = RunState.failed(run_id)
        else:
            self.scheduler.schedule(run_id)
        return failure

    def wake_count(self, run_id: str) -> int:
        return self._wake_counts.get(run_id, 0)

    def task(self, task_id: str) -> Task:
        return self.scheduler.tasks[task_id].task

    def _select_for_scheduler(
        self, stage: str, capabilities: tuple[str, ...]
    ) -> AgentProfile | None:
        return self.choose_profile(stage, capabilities)

    def _refresh_run_status(self, run_id: str) -> None:
        tasks = tuple(
            spec.task for spec in self.scheduler.tasks.values() if spec.task.run_id == run_id
        )
        if tasks and all(task.status.value == "completed" for task in tasks):
            self._run_states[run_id] = RunState.completed(run_id)

    def _append_event(self, run_id: str, event: LedgerEvent) -> None:
        append = getattr(self.ledger, "append", None)
        if callable(append):
            append(run_id, event)

    def _record_failure(self, run_id: str, failure: AttemptFailed) -> None:
        """Persist a structured failure without assuming a new EventType."""

        record = getattr(self.ledger, "record_failure", None)
        if callable(record):
            record(run_id, failure)
            return
        record = getattr(self.ledger, "append_attempt_failed", None)
        if callable(record):
            record(run_id, failure)


CoordinatorSession = Coordinator

__all__ = ["Coordinator", "CoordinatorLedger", "CoordinatorSession", "CoordinatorWake"]
