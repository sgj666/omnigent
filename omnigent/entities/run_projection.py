"""Provider-neutral records for Session-backed Run projections."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    CREATING = "creating"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorktreeLeaseStatus(StrEnum):
    ACTIVE = "active"
    RECOVERY_REQUIRED = "recovery_required"
    RELEASED = "released"


@dataclass(frozen=True)
class RunCreate:
    agent_id: str
    input: str
    source: str
    source_event_id: str
    workspace_id: str | None = None
    host_id: str | None = None
    execution_mode: str = "auto"


@dataclass(frozen=True)
class Run:
    id: str
    actor_id: str
    auth_scope: str
    source: str
    source_event_id: str
    agent_id: str
    bundle_version: int
    bundle_digest: str
    bundle_location: str
    workspace_id: str
    root_session_id: str | None
    status: RunStatus
    created_at: int
    updated_at: int | None = None


@dataclass(frozen=True)
class Task:
    id: str
    run_id: str
    title: str
    status: TaskStatus
    root_session_id: str | None = None
    child_session_id: str | None = None
    dispatch_title: str | None = None
    purpose: str | None = None
    source_event_id: str | None = None
    created_at: int = 0
    updated_at: int | None = None


@dataclass(frozen=True)
class Attempt:
    id: str
    task_id: str
    status: AttemptStatus
    child_session_id: str | None = None
    worker_name: str | None = None
    worker_config_path: str | None = None
    purpose: str | None = None
    harness: str | None = None
    model: str | None = None
    dispatch_call_id: str | None = None
    response_id: str | None = None
    turn_id: str | None = None
    started_at: int | None = None
    completed_at: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    retry_of_attempt_id: str | None = None
    source_event_id: str | None = None
    created_at: int = 0
    updated_at: int | None = None


@dataclass(frozen=True)
class ProjectionEvent:
    source: str
    source_event_id: str
    event_type: str
    run_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    attempt_id: str | None = None
    session_id: str | None = None
    conversation_item_id: str | None = None


@dataclass(frozen=True)
class ProjectionResult:
    created: bool
    event: ProjectionEvent
    task: Task | None = None
    attempt: Attempt | None = None


@dataclass(frozen=True)
class CreateRunResult:
    run: Run
    created: bool


@dataclass(frozen=True)
class WorkspaceRepository:
    id: str
    name: str
    path: str


@dataclass(frozen=True)
class Workspace:
    id: str
    root_path: str
    repositories: tuple[WorkspaceRepository, ...]
    created_at: int


@dataclass(frozen=True)
class WorktreeLease:
    id: str
    run_id: str
    attempt_id: str | None
    child_session_id: str
    host_id: str
    repository_id: str
    worktree_path: str
    branch: str
    owner_id: str
    status: WorktreeLeaseStatus
    heartbeat_at: int
    base_commit: str | None
    output_commit: str | None
    created_at: int
    released_at: int | None = None


@dataclass(frozen=True)
class InspectorFailure:
    attempt_id: str | None
    code: str
    message: str


@dataclass(frozen=True)
class InspectorAgentSnapshot:
    id: str
    bundle_version: int
    bundle_digest: str
    bundle_location: str


@dataclass(frozen=True)
class InspectorSessionReference:
    id: str
    kind: str


@dataclass(frozen=True)
class InspectorDependency:
    task_id: str
    depends_on_task_id: str


@dataclass(frozen=True)
class InspectorLogReference:
    session_id: str
    href: str


@dataclass(frozen=True)
class InspectorArtifactReference:
    id: str
    task_id: str | None
    attempt_id: str | None
    name: str
    location: str
    content_type: str | None
    created_at: int


@dataclass(frozen=True)
class InspectorRun:
    run: Run
    root_session_id: str | None
    child_session_ids: tuple[str, ...]
    conversation_item_ids: tuple[str, ...]
    tasks: tuple[Task, ...]
    attempts: tuple[Attempt, ...]
    failures: tuple[InspectorFailure, ...]
    agent_snapshot: InspectorAgentSnapshot | None = None
    workspace: Workspace | None = None
    sessions: tuple[InspectorSessionReference, ...] = ()
    dependencies: tuple[InspectorDependency, ...] = ()
    events: tuple[ProjectionEvent, ...] = ()
    leases: tuple[WorktreeLease, ...] = ()
    log_references: tuple[InspectorLogReference, ...] = ()
    artifact_references: tuple[InspectorArtifactReference, ...] = ()
