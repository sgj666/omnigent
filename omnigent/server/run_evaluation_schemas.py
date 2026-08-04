"""Request and response schemas for the isolated Run evaluation API."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from omnigent.entities.run_evaluation import EvaluationRecord


class EvaluateRunRequest(BaseModel):
    """Request an idempotent evaluation or explicit refresh."""

    model_config = ConfigDict(extra="forbid")

    refresh: bool = False


class EvidenceCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worktree: int
    commit: int
    artifact: int
    test: int
    session: int
    conversation_item: int


class EvaluationMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    failure_categories: dict[str, int]
    evidence_counts: EvidenceCountsResponse


class WorkerEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_name: str
    session_ids: tuple[str, ...]
    task_count: int
    attempt_count: int
    success_count: int
    retry_count: int
    blocked_count: int
    blocked_duration_seconds: float
    duration_seconds: float
    failure_categories: dict[str, int]


class RunEvaluationResponse(BaseModel):
    """Safe collaboration metrics and evidence references for one Run."""

    model_config = ConfigDict(extra="forbid")

    object: Literal["run.evaluation"] = "run.evaluation"
    id: str
    run_id: str
    evaluator: str
    version: int
    status: Literal["preview", "final"]
    metrics: EvaluationMetricsResponse
    workers: tuple[WorkerEvaluationResponse, ...]
    evidence_refs: tuple[str, ...]
    rubric: dict[str, Any] | None
    created_at: int
    updated_at: int


def evaluation_response(record: EvaluationRecord) -> RunEvaluationResponse:
    """Convert the internal owner-bearing record to its public safe DTO."""
    payload = asdict(record)
    payload.pop("owner_user_id")
    return RunEvaluationResponse.model_validate(payload | {"object": "run.evaluation"})
