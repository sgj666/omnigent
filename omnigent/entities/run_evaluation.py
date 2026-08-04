"""Provider-neutral records for deterministic Run collaboration evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EvaluationStatus(StrEnum):
    """Whether metrics describe an active preview or terminal Run."""

    PREVIEW = "preview"
    FINAL = "final"


class FailureCategory(StrEnum):
    """Stable high-level taxonomy for observed attempt failures."""

    BLOCKED = "blocked"
    TEST = "test"
    TIMEOUT = "timeout"
    AUTHORIZATION = "authorization"
    INFRASTRUCTURE = "infrastructure"
    CANCELLED = "cancelled"
    WORKER = "worker"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidenceCounts:
    """Counts of safe references; never transcript or event payload content."""

    worktree: int = 0
    commit: int = 0
    artifact: int = 0
    test: int = 0
    session: int = 0
    conversation_item: int = 0


@dataclass(frozen=True)
class EvaluationMetrics:
    """Run-level collaboration effectiveness metrics."""

    task_completion_rate: float
    attempt_success_rate: float
    retry_count: int
    blocked_count: int
    blocked_duration_seconds: float
    parallel_overlap_seconds: float
    max_concurrency: int
    worker_duration_seconds: float
    parent_inbox_latency_seconds: float | None
    parent_inbox_latency_samples: int
    failure_categories: dict[str, int] = field(default_factory=dict)
    evidence_counts: EvidenceCounts = field(default_factory=EvidenceCounts)


@dataclass(frozen=True)
class WorkerEvaluation:
    """Deterministic metrics for one projected worker identity."""

    worker_name: str
    session_ids: tuple[str, ...]
    task_count: int
    attempt_count: int
    success_count: int
    retry_count: int
    blocked_count: int
    blocked_duration_seconds: float
    duration_seconds: float
    failure_categories: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationRecord:
    """One idempotent evaluator/version result for a Run owner."""

    id: str
    run_id: str
    owner_user_id: str
    evaluator: str
    version: int
    status: EvaluationStatus
    metrics: EvaluationMetrics
    workers: tuple[WorkerEvaluation, ...]
    evidence_refs: tuple[str, ...]
    rubric: dict[str, Any] | None
    created_at: int
    updated_at: int
