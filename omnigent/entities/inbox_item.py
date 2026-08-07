"""Persistent user-facing Inbox item."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InboxItemKind(StrEnum):
    """Lifecycle facts surfaced in the product Inbox."""

    APPROVAL_REQUIRED = "approval_required"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    TASK_WAITING = "task_waiting"
    TASK_SUCCEEDED = "task_succeeded"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    TASK_COMPLETED = "task_completed"


@dataclass
class InboxItem:
    """One durable, owner-private Inbox notification."""

    id: str
    owner_user_id: str | None
    kind: InboxItemKind
    dedupe_key: str
    work_item_id: str | None
    work_item_run_id: str | None
    session_id: str | None
    source_id: str | None
    message: str | None
    target_url: str
    action_required: bool
    created_at: int
    updated_at: int | None
    read_at: int | None
    resolved_at: int | None
