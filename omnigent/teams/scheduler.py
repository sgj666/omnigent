"""Deterministic task-DAG scheduling primitives for team harness runs.

The scheduler deliberately owns only orchestration state.  Durable event
storage and worktree leases are supplied as small callbacks so this module is
useful in tests as well as in the server runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from uuid import uuid4

from omnigent.entities.run import Attempt, AttemptStatus, Task, TaskStatus
from omnigent.entities.team import AgentProfile


@dataclass(frozen=True)
class AttemptFailed:
    """Structured, user-actionable diagnostics for a failed attempt."""

    attempt_id: str
    task_id: str
    failure_code: str
    exit_code: int | None
    last_tool_call: str | None
    log_ref: str | None
    retry_count: int
    suggested_action: str
    hard_block: bool = False


@dataclass
class TaskSpec:
    """Scheduling metadata that does not belong in the base Task entity."""

    task: Task
    stage: str = "implementation"
    required_capabilities: tuple[str, ...] = ()
    profile_id: str | None = None
    max_retries: int = 0
    retry_count: int = 0
    current_attempt_id: str | None = None
    attempts: list[Attempt] = field(default_factory=list)


ProfileSelector = Callable[[str, tuple[str, ...]], AgentProfile | None]
LeaseAcquirer = Callable[[Task, AgentProfile], bool]


class DAGScheduler:
    """A small deterministic scheduler for independent and dependent tasks."""

    def __init__(
        self,
        profiles: Iterable[AgentProfile] = (),
        *,
        team_concurrency: int | None = None,
        profile_concurrency: Mapping[str, int] | None = None,
        profile_selector: ProfileSelector | None = None,
        lease_acquirer: LeaseAcquirer | None = None,
    ) -> None:
        self.profiles = {profile.id: profile for profile in profiles}
        self.team_concurrency = team_concurrency
        self.profile_concurrency = dict(profile_concurrency or {})
        self.profile_selector = profile_selector
        self.lease_acquirer = lease_acquirer or (lambda _task, _profile: True)
        self.tasks: dict[str, TaskSpec] = {}
        self.attempts: dict[str, Attempt] = {}
        self.failures: list[AttemptFailed] = []

    def add_task(
        self,
        task: Task,
        *,
        stage: str = "implementation",
        required_capabilities: Iterable[str] = (),
        profile_id: str | None = None,
        max_retries: int = 0,
    ) -> TaskSpec:
        if task.id in self.tasks:
            raise ValueError(f"task {task.id!r} already exists")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        spec = TaskSpec(
            task=task,
            stage=stage,
            required_capabilities=tuple(required_capabilities),
            profile_id=profile_id,
            max_retries=max_retries,
        )
        self.tasks[task.id] = spec
        return spec

    def add_dependency(self, task_id: str, depends_on: str) -> None:
        spec = self._spec(task_id)
        self._spec(depends_on)
        if depends_on == task_id:
            raise ValueError("a task cannot depend on itself")
        if depends_on not in spec.task.depends_on:
            spec.task.depends_on.append(depends_on)
        try:
            self._assert_acyclic()
        except ValueError:
            spec.task.depends_on.remove(depends_on)
            raise

    def ready_tasks(self, run_id: str | None = None) -> tuple[Task, ...]:
        """Return pending tasks whose dependencies have all completed."""

        return tuple(
            spec.task
            for spec in self.tasks.values()
            if (run_id is None or spec.task.run_id == run_id)
            and spec.task.status is TaskStatus.PENDING
            and all(
                self._spec(dep).task.status is TaskStatus.COMPLETED
                for dep in spec.task.depends_on
            )
        )

    def schedule(self, run_id: str | None = None) -> tuple[Attempt, ...]:
        """Start as many ready tasks as the team/profile quotas allow."""

        started: list[Attempt] = []
        for task in self.ready_tasks(run_id):
            spec = self.tasks[task.id]
            profile = self._profile_for(spec)
            if profile is None or not self._capacity_available(profile.id):
                continue
            if not self.lease_acquirer(task, profile):
                continue
            attempt = Attempt(
                id=uuid4().hex,
                task_id=task.id,
                agent_profile_id=profile.id,
                status=AttemptStatus.RUNNING,
            )
            task.status = TaskStatus.RUNNING
            spec.current_attempt_id = attempt.id
            spec.attempts.append(attempt)
            self.attempts[attempt.id] = attempt
            started.append(attempt)
        return tuple(started)

    def complete(self, task_id: str, attempt_id: str) -> bool:
        """Mark one attempt and its task complete; repeated completion is safe."""

        spec = self._spec(task_id)
        attempt = self._attempt(attempt_id)
        if attempt.task_id != task_id:
            raise ValueError("attempt does not belong to task")
        if attempt.status is AttemptStatus.SUCCEEDED:
            return False
        if attempt.status is not AttemptStatus.RUNNING:
            return False
        attempt.status = AttemptStatus.SUCCEEDED
        spec.task.status = TaskStatus.COMPLETED
        return True

    def fail(
        self,
        task_id: str,
        attempt_id: str,
        *,
        failure_code: str,
        exit_code: int | None = None,
        last_tool_call: str | None = None,
        log_ref: str | None = None,
        suggested_action: str = "inspect logs and retry",
    ) -> AttemptFailed:
        spec = self._spec(task_id)
        attempt = self._attempt(attempt_id)
        if attempt.task_id != task_id:
            raise ValueError("attempt does not belong to task")
        if attempt.status is AttemptStatus.FAILED:
            return next(item for item in reversed(self.failures) if item.attempt_id == attempt_id)
        if attempt.status is not AttemptStatus.RUNNING:
            raise ValueError("only a running attempt can fail")
        attempt.status = AttemptStatus.FAILED
        spec.retry_count += 1
        hard_block = spec.retry_count > spec.max_retries
        if hard_block:
            spec.task.status = TaskStatus.FAILED
            action = suggested_action or "resolve the hard block"
        else:
            spec.task.status = TaskStatus.PENDING
            spec.current_attempt_id = None
            action = suggested_action or "retry the attempt"
        result = AttemptFailed(
            attempt_id=attempt_id,
            task_id=task_id,
            failure_code=failure_code,
            exit_code=exit_code,
            last_tool_call=last_tool_call,
            log_ref=log_ref,
            retry_count=spec.retry_count,
            suggested_action=action,
            hard_block=hard_block,
        )
        self.failures.append(result)
        return result

    def active_attempts(self) -> tuple[Attempt, ...]:
        return tuple(
            attempt
            for attempt in self.attempts.values()
            if attempt.status is AttemptStatus.RUNNING
        )

    def _profile_for(self, spec: TaskSpec) -> AgentProfile | None:
        required = set(spec.required_capabilities)
        if spec.profile_id is not None:
            profile = self.profiles.get(spec.profile_id)
            if profile is not None and required.issubset(profile.capabilities):
                return profile
            return None
        if self.profile_selector is not None:
            profile = self.profile_selector(spec.stage, spec.required_capabilities)
            if (
                profile is not None
                and profile.id in self.profiles
                and required.issubset(profile.capabilities)
            ):
                return profile
            return None
        for profile in self.profiles.values():
            if required.issubset(profile.capabilities):
                return profile
        return None

    def _capacity_available(self, profile_id: str) -> bool:
        active = self.active_attempts()
        if self.team_concurrency is not None and len(active) >= self.team_concurrency:
            return False
        limit = self.profile_concurrency.get(profile_id)
        if limit is not None and sum(
            item.agent_profile_id == profile_id for item in active
        ) >= limit:
            return False
        return True

    def _spec(self, task_id: str) -> TaskSpec:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown task {task_id!r}") from exc

    def _attempt(self, attempt_id: str) -> Attempt:
        try:
            return self.attempts[attempt_id]
        except KeyError as exc:
            raise KeyError(f"unknown attempt {attempt_id!r}") from exc

    def _assert_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("task dependencies must form a DAG")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self._spec(task_id).task.depends_on:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self.tasks:
            visit(task_id)


TaskScheduler = DAGScheduler
Scheduler = DAGScheduler

__all__ = ["AttemptFailed", "DAGScheduler", "Scheduler", "TaskScheduler", "TaskSpec"]
