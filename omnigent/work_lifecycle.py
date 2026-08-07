"""Shared Task, TaskRun, and Inbox lifecycle contracts.

These models define the Phase 0 wire contract only. Persistence and delivery
policy belong to the Task and Inbox services introduced in Phase 2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class TaskState(StrEnum):
    """User-facing Task workflow states."""

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRunState(StrEnum):
    """Execution states for one TaskRun."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRunTrigger(StrEnum):
    """Why a TaskRun was created."""

    MANUAL = "manual"
    RETRY = "retry"


class TaskLifecycleEventType(StrEnum):
    """Stable lifecycle event names shared by API and clients."""

    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_CANCELLED = "task.cancelled"
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_PROGRESS = "run.progress"
    RUN_WAITING = "run.waiting"
    RUN_SUCCEEDED = "run.succeeded"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"


class InboxCategory(StrEnum):
    """User-facing Inbox projection categories."""

    ACTION_REQUIRED = "action_required"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"


class LifecycleEventSource(BaseModel):
    """Actor or subsystem that produced a lifecycle event."""

    kind: str = Field(min_length=1, max_length=64)
    id: str | None = Field(default=None, min_length=1, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=256)

    model_config = ConfigDict(extra="forbid")


class RequiredAction(BaseModel):
    """Action metadata attached to a waiting event or Inbox item."""

    action_id: str = Field(min_length=1, max_length=256)
    kind: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=4000)
    expires_at: AwareDatetime | None = None

    model_config = ConfigDict(extra="forbid")


class FailureDetails(BaseModel):
    """Structured failure information safe to show in management views."""

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    retryable: bool = False

    model_config = ConfigDict(extra="forbid")


class ResultDetails(BaseModel):
    """Compact result metadata; artifacts remain referenced, not embedded."""

    summary: str | None = Field(default=None, max_length=4000)
    artifact_ids: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TaskLifecycleEvent(BaseModel):
    """Normalized immutable fact emitted by Task and TaskRun workflows."""

    event_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=512)
    type: TaskLifecycleEventType
    occurred_at: AwareDatetime
    task_id: str = Field(min_length=1, max_length=256)
    run_id: str | None = Field(default=None, min_length=1, max_length=256)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    project_id: str | None = Field(default=None, min_length=1, max_length=256)
    source: LifecycleEventSource
    summary: str = Field(min_length=1, max_length=1000)
    task_state: TaskState | None = None
    run_state: TaskRunState | None = None
    action: RequiredAction | None = None
    failure: FailureDetails | None = None
    result: ResultDetails | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_event_shape(self) -> TaskLifecycleEvent:
        """Require execution identity and failure details when relevant."""
        if self.type.value.startswith("run.") and self.run_id is None:
            raise ValueError("run lifecycle events require run_id")
        if self.type is TaskLifecycleEventType.RUN_FAILED and self.failure is None:
            raise ValueError("run.failed events require failure details")
        return self


class InboxItemProjection(BaseModel):
    """Persistent Inbox view projected from one lifecycle event."""

    item_id: str = Field(min_length=1, max_length=256)
    dedupe_key: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=256)
    category: InboxCategory
    task_id: str = Field(min_length=1, max_length=256)
    run_id: str | None = Field(default=None, min_length=1, max_length=256)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)
    project_id: str | None = Field(default=None, min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=1000)
    action: RequiredAction | None = None
    is_unread: bool
    created_at: AwareDatetime

    model_config = ConfigDict(extra="forbid")
