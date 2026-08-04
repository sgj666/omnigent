"""Pure aggregation of Run Inspector and projection-event facts."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from omnigent.db.utils import now_epoch
from omnigent.entities.run_evaluation import (
    EvaluationMetrics,
    EvaluationRecord,
    EvaluationStatus,
    EvidenceCounts,
    FailureCategory,
    WorkerEvaluation,
)
from omnigent.entities.run_projection import (
    Attempt,
    AttemptStatus,
    InspectorRun,
    ProjectionEvent,
    RunStatus,
    TaskStatus,
)
from omnigent.errors import ErrorCode, OmnigentError

DEFAULT_EVALUATOR = "session-collaboration"
DEFAULT_EVALUATOR_VERSION = 1
_TERMINAL_RUN_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
_TERMINAL_EVENT_TYPES = {
    "session.completed",
    "session.failed",
    "session.cancelled",
    "session.running",
}


class RunEvaluationSource(Protocol):
    """Read-only Run projection surface needed by the evaluator."""

    def inspect_run(self, run_id: str) -> InspectorRun: ...

    def list_projection_events(self, run_id: str) -> tuple[ProjectionEvent, ...]: ...


class EvaluationStore(Protocol):
    """Minimal persistence seam for idempotent records."""

    def get(
        self,
        *,
        run_id: str,
        evaluator: str,
        version: int,
        owner_user_id: str,
    ) -> EvaluationRecord | None: ...

    def upsert(self, record: EvaluationRecord) -> EvaluationRecord: ...


RubricEvaluator = Callable[[InspectorRun, EvaluationMetrics], dict[str, Any]]


@dataclass(frozen=True)
class _AttemptFacts:
    attempt: Attempt
    start: float
    end: float
    duration: float


class RunEvaluationService:
    """Versioned evaluator that never starts, retries, or wakes an Agent."""

    def __init__(
        self,
        run_source: RunEvaluationSource,
        *,
        evaluation_store: EvaluationStore | None = None,
        rubric_evaluator: RubricEvaluator | None = None,
        evaluator: str = DEFAULT_EVALUATOR,
        version: int = DEFAULT_EVALUATOR_VERSION,
        clock: Callable[[], int] = now_epoch,
    ) -> None:
        self._run_source = run_source
        self._evaluation_store = evaluation_store
        self._rubric_evaluator = rubric_evaluator
        self.evaluator = evaluator
        self.version = version
        self._clock = clock

    def get_or_evaluate(self, run_id: str, *, owner_user_id: str) -> EvaluationRecord:
        """Return a current preview/final record, evaluating on first read."""
        inspector = self._owned_inspector(run_id, owner_user_id)
        existing = self._stored(run_id, owner_user_id)
        expected = _evaluation_status(inspector.run.status)
        if existing is not None and existing.status is expected:
            return existing
        return self._evaluate(inspector, owner_user_id, existing=existing)

    def evaluate(
        self,
        run_id: str,
        *,
        owner_user_id: str,
        refresh: bool = False,
    ) -> EvaluationRecord:
        """Evaluate a Run, or return its idempotently stored evaluator version."""
        inspector = self._owned_inspector(run_id, owner_user_id)
        existing = self._stored(run_id, owner_user_id)
        expected = _evaluation_status(inspector.run.status)
        if not refresh and existing is not None and existing.status is expected:
            return existing
        return self._evaluate(inspector, owner_user_id, existing=existing)

    def _owned_inspector(self, run_id: str, owner_user_id: str) -> InspectorRun:
        try:
            inspector = self._run_source.inspect_run(run_id)
        except ValueError as exc:
            raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND) from exc
        if inspector.run.actor_id != owner_user_id:
            raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
        return inspector

    def _stored(self, run_id: str, owner_user_id: str) -> EvaluationRecord | None:
        if self._evaluation_store is None:
            return None
        return self._evaluation_store.get(
            run_id=run_id,
            evaluator=self.evaluator,
            version=self.version,
            owner_user_id=owner_user_id,
        )

    def _evaluate(
        self,
        inspector: InspectorRun,
        owner_user_id: str,
        *,
        existing: EvaluationRecord | None,
    ) -> EvaluationRecord:
        events = self._run_source.list_projection_events(inspector.run.id)
        timestamp = self._clock()
        metrics, workers, evidence_refs = evaluate_projection(inspector, events, now=timestamp)
        rubric = (
            self._rubric_evaluator(inspector, metrics)
            if self._rubric_evaluator is not None
            else None
        )
        record = EvaluationRecord(
            id=(
                existing.id
                if existing is not None
                else uuid5(
                    NAMESPACE_URL,
                    f"omnigent:{inspector.run.id}:{self.evaluator}:{self.version}",
                ).hex
            ),
            run_id=inspector.run.id,
            owner_user_id=owner_user_id,
            evaluator=self.evaluator,
            version=self.version,
            status=_evaluation_status(inspector.run.status),
            metrics=metrics,
            workers=workers,
            evidence_refs=evidence_refs,
            rubric=rubric,
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
        )
        if self._evaluation_store is None:
            return record
        return self._evaluation_store.upsert(record)


def evaluate_projection(
    inspector: InspectorRun,
    events: tuple[ProjectionEvent, ...],
    *,
    now: int,
) -> tuple[EvaluationMetrics, tuple[WorkerEvaluation, ...], tuple[str, ...]]:
    """Calculate metrics exclusively from safe projection facts and references."""
    attempts = tuple(_attempt_facts(attempt, inspector, now) for attempt in inspector.attempts)
    blocked_by_attempt = _blocked_durations(inspector, events, now)
    failure_by_attempt = _failures(inspector)
    evidence_counts, evidence_refs = _evidence(inspector, events)
    tasks_by_worker: dict[str, set[str]] = defaultdict(set)
    attempts_by_worker: dict[str, list[_AttemptFacts]] = defaultdict(list)
    task_ids = {attempt.id: attempt.task_id for attempt in inspector.attempts}
    for facts in attempts:
        worker = facts.attempt.worker_name or facts.attempt.child_session_id or "unknown-worker"
        attempts_by_worker[worker].append(facts)
        tasks_by_worker[worker].add(facts.attempt.task_id)

    workers = tuple(
        _worker_evaluation(
            worker,
            worker_attempts,
            tasks_by_worker[worker],
            blocked_by_attempt,
            failure_by_attempt,
        )
        for worker, worker_attempts in sorted(attempts_by_worker.items())
    )
    failure_categories = Counter(
        category.value for categories in failure_by_attempt.values() for category in categories
    )
    blocked_attempts = {
        attempt_id for attempt_id, duration in blocked_by_attempt.items() if duration >= 0
    }
    blocked_attempts.update(
        attempt.id for attempt in inspector.attempts if attempt.status is AttemptStatus.BLOCKED
    )
    overlap, max_concurrency = _parallel_metrics(attempts)
    latencies = _parent_inbox_latencies(inspector, events)
    task_count = len(inspector.tasks)
    attempt_count = len(inspector.attempts)
    retry_count = attempt_count - len(set(task_ids.values())) if attempt_count else 0
    metrics = EvaluationMetrics(
        task_completion_rate=(
            sum(task.status is TaskStatus.COMPLETED for task in inspector.tasks) / task_count
            if task_count
            else 0.0
        ),
        attempt_success_rate=(
            sum(attempt.status is AttemptStatus.SUCCEEDED for attempt in inspector.attempts)
            / attempt_count
            if attempt_count
            else 0.0
        ),
        retry_count=max(0, retry_count),
        blocked_count=len(blocked_attempts),
        blocked_duration_seconds=sum(blocked_by_attempt.values()),
        parallel_overlap_seconds=overlap,
        max_concurrency=max_concurrency,
        worker_duration_seconds=sum(facts.duration for facts in attempts),
        parent_inbox_latency_seconds=(sum(latencies) / len(latencies) if latencies else None),
        parent_inbox_latency_samples=len(latencies),
        failure_categories=dict(sorted(failure_categories.items())),
        evidence_counts=evidence_counts,
    )
    return metrics, workers, evidence_refs


def _attempt_facts(attempt: Attempt, inspector: InspectorRun, now: int) -> _AttemptFacts:
    start = float(attempt.started_at if attempt.started_at is not None else attempt.created_at)
    end_value = attempt.completed_at or attempt.updated_at or inspector.run.updated_at or now
    end = float(max(start, end_value))
    return _AttemptFacts(attempt=attempt, start=start, end=end, duration=end - start)


def _worker_evaluation(
    worker: str,
    attempts: list[_AttemptFacts],
    task_ids: set[str],
    blocked_by_attempt: dict[str, float],
    failure_by_attempt: dict[str, tuple[FailureCategory, ...]],
) -> WorkerEvaluation:
    failures = Counter(
        category.value
        for facts in attempts
        for category in failure_by_attempt.get(facts.attempt.id, ())
    )
    blocked_ids = {
        facts.attempt.id
        for facts in attempts
        if facts.attempt.id in blocked_by_attempt or facts.attempt.status is AttemptStatus.BLOCKED
    }
    sessions = tuple(
        dict.fromkeys(
            facts.attempt.child_session_id
            for facts in attempts
            if facts.attempt.child_session_id is not None
        )
    )
    return WorkerEvaluation(
        worker_name=worker,
        session_ids=sessions,
        task_count=len(task_ids),
        attempt_count=len(attempts),
        success_count=sum(facts.attempt.status is AttemptStatus.SUCCEEDED for facts in attempts),
        retry_count=max(0, len(attempts) - len(task_ids)),
        blocked_count=len(blocked_ids),
        blocked_duration_seconds=sum(
            blocked_by_attempt.get(attempt_id, 0) for attempt_id in blocked_ids
        ),
        duration_seconds=sum(facts.duration for facts in attempts),
        failure_categories=dict(sorted(failures.items())),
    )


def _parallel_metrics(attempts: tuple[_AttemptFacts, ...]) -> tuple[float, int]:
    changes: dict[float, int] = defaultdict(int)
    for facts in attempts:
        if facts.duration <= 0 or facts.attempt.status in {
            AttemptStatus.BLOCKED,
            AttemptStatus.QUEUED,
        }:
            continue
        changes[facts.start] += 1
        changes[facts.end] -= 1
    active = 0
    maximum = 0
    overlap = 0.0
    previous: float | None = None
    for timestamp in sorted(changes):
        if previous is not None and active >= 2:
            overlap += timestamp - previous
        active += changes[timestamp]
        maximum = max(maximum, active)
        previous = timestamp
    return overlap, maximum


def _blocked_durations(
    inspector: InspectorRun,
    events: tuple[ProjectionEvent, ...],
    now: int,
) -> dict[str, float]:
    timelines: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for event in events:
        timestamp = _event_time(event)
        if event.attempt_id is not None and timestamp is not None:
            timelines[event.attempt_id].append((timestamp, event.event_type))
    attempts = {attempt.id: attempt for attempt in inspector.attempts}
    durations: dict[str, float] = {}
    for attempt_id, timeline in timelines.items():
        ordered = sorted(timeline)
        total = 0.0
        saw_blocked = False
        for index, (start, event_type) in enumerate(ordered):
            if event_type != "session.blocked":
                continue
            saw_blocked = True
            end = next(
                (
                    timestamp
                    for timestamp, next_type in ordered[index + 1 :]
                    if next_type in _TERMINAL_EVENT_TYPES
                ),
                None,
            )
            if end is None:
                attempt = attempts.get(attempt_id)
                end = float(
                    (attempt.completed_at or attempt.updated_at or inspector.run.updated_at or now)
                    if attempt is not None
                    else now
                )
            total += max(0.0, end - start)
        if saw_blocked:
            durations[attempt_id] = total
    for attempt in inspector.attempts:
        if attempt.status is AttemptStatus.BLOCKED and attempt.id not in durations:
            start = float(attempt.started_at or attempt.created_at)
            end = float(attempt.updated_at or inspector.run.updated_at or now)
            durations[attempt.id] = max(0.0, end - start)
    return durations


def _parent_inbox_latencies(
    inspector: InspectorRun, events: tuple[ProjectionEvent, ...]
) -> tuple[float, ...]:
    timed = tuple(
        (timestamp, event) for event in events if (timestamp := _event_time(event)) is not None
    )
    root_activity = sorted(
        timestamp
        for timestamp, event in timed
        if event.session_id == inspector.root_session_id
        and event.event_type not in {"run.root.created", "plan.dependency"}
    )
    latencies: list[float] = []
    for relayed_at, event in timed:
        if event.event_type != "parent_inbox.relayed":
            continue
        next_activity = next((value for value in root_activity if value >= relayed_at), None)
        if next_activity is not None:
            latencies.append(next_activity - relayed_at)
    return tuple(latencies)


def _failures(inspector: InspectorRun) -> dict[str, tuple[FailureCategory, ...]]:
    failures: dict[str, list[FailureCategory]] = defaultdict(list)
    for failure in inspector.failures:
        category = classify_failure(failure.code)
        if category not in failures[failure.attempt_id]:
            failures[failure.attempt_id].append(category)
    return {attempt_id: tuple(categories) for attempt_id, categories in failures.items()}


def classify_failure(code: str) -> FailureCategory:
    """Map a provider-specific code into the stable evaluation taxonomy."""
    normalized = code.lower()
    if "block" in normalized or "approval" in normalized:
        return FailureCategory.BLOCKED
    if "test" in normalized or "assert" in normalized:
        return FailureCategory.TEST
    if "timeout" in normalized or "deadline" in normalized:
        return FailureCategory.TIMEOUT
    if any(value in normalized for value in ("auth", "permission", "forbidden")):
        return FailureCategory.AUTHORIZATION
    if any(value in normalized for value in ("runner", "transport", "network", "crash")):
        return FailureCategory.INFRASTRUCTURE
    if "cancel" in normalized:
        return FailureCategory.CANCELLED
    if "worker" in normalized or "agent" in normalized:
        return FailureCategory.WORKER
    return FailureCategory.UNKNOWN


def _evidence(
    inspector: InspectorRun, events: tuple[ProjectionEvent, ...]
) -> tuple[EvidenceCounts, tuple[str, ...]]:
    sessions = set(inspector.child_session_ids) | {inspector.root_session_id}
    items = set(inspector.conversation_item_ids)
    refs = {f"session:{session_id}" for session_id in sessions}
    refs.update(f"conversation_item:{item_id}" for item_id in items)
    worktrees: set[str] = set()
    commits: set[str] = set()
    artifacts: set[str] = set()
    tests: set[str] = set()
    for event in events:
        refs.add(f"event:{event.source}:{event.source_event_id}")
        if event.session_id is not None:
            sessions.add(event.session_id)
            refs.add(f"session:{event.session_id}")
        if event.conversation_item_id is not None:
            items.add(event.conversation_item_id)
            refs.add(f"conversation_item:{event.conversation_item_id}")
        if event.event_type.startswith("worktree."):
            worktrees.add(event.source_event_id)
        if event.event_type.startswith("commit.") or "output_commit" in event.payload:
            commits.add(event.source_event_id)
        if event.event_type.startswith("artifact."):
            artifacts.add(event.source_event_id)
        if event.event_type.startswith("test."):
            tests.add(event.source_event_id)
    return (
        EvidenceCounts(
            worktree=len(worktrees),
            commit=len(commits),
            artifact=len(artifacts),
            test=len(tests),
            session=len(sessions),
            conversation_item=len(items),
        ),
        tuple(sorted(refs)),
    )


def _event_time(event: ProjectionEvent) -> float | None:
    value = event.payload.get("occurred_at")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _evaluation_status(status: RunStatus) -> EvaluationStatus:
    return EvaluationStatus.FINAL if status in _TERMINAL_RUN_STATUSES else EvaluationStatus.PREVIEW
