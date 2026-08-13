"""Durable development-delivery workflow state for an Ominigent Run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DeliveryPhase(StrEnum):
    INTAKE = "intake"
    PREFLIGHT = "preflight"
    REQUIREMENT = "requirement"
    RESEARCH = "research"
    PROPOSAL = "proposal"
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    INTEGRATION = "integration"
    TESTING = "testing"
    VERIFICATION = "verification"
    REVIEW = "review"
    KNOWLEDGE_CLOSE = "knowledge_close"
    ARCHIVE = "archive"
    PENDING_DELIVERY = "pending_delivery"
    DELIVERED = "delivered"


class DeliveryStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class PlannedTaskStatus(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class DeliveryRun:
    id: str
    runtime_run_id: str
    profile_id: str
    owner_user_id: str
    phase: DeliveryPhase
    status: DeliveryStatus
    version: int
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class PlannedTask:
    id: str
    delivery_run_id: str
    task_key: str
    title: str
    owner_role: str
    status: PlannedTaskStatus = PlannedTaskStatus.PLANNED
    depends_on: tuple[str, ...] = ()
    artifact_requirements: tuple[str, ...] = ()
    created_at: int = 0
    updated_at: int = 0


@dataclass(frozen=True)
class DeliveryArtifact:
    id: str
    delivery_run_id: str
    kind: str
    location: str
    content_sha256: str
    planned_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


@dataclass(frozen=True)
class DeliveryTransition:
    id: str
    delivery_run_id: str
    profile_id: str
    idempotency_key: str
    from_phase: DeliveryPhase
    to_phase: DeliveryPhase
    from_status: DeliveryStatus
    to_status: DeliveryStatus
    expected_version: int
    result_version: int
    evidence_refs: tuple[str, ...]
    actor_id: str
    created_at: int


@dataclass(frozen=True)
class DeliveryWorkflowSnapshot:
    run: DeliveryRun
    planned_tasks: tuple[PlannedTask, ...] = ()
    artifacts: tuple[DeliveryArtifact, ...] = ()
    transitions: tuple[DeliveryTransition, ...] = ()
