"""Product Task entity persisted in ``work_items``."""

from __future__ import annotations

from dataclasses import dataclass

from omnigent.work_lifecycle import TaskState


@dataclass
class WorkItem:
    """A durable user-facing Task, distinct from run tasks and automations."""

    id: str
    owner_user_id: str | None
    title: str
    description: str | None
    state: TaskState
    priority: str
    project_id: str | None
    assignee_agent_id: str | None
    due_at: int | None
    created_at: int
    updated_at: int | None
    completed_at: int | None
    version: int
    completion_id: str | None = None
    creator_kind: str = "user"
    created_by_agent_id: str | None = None
