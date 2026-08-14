"""Persistence contract for user-facing product Tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from omnigent.entities import WorkItem


class WorkItemStore(ABC):
    """Owner-scoped CRUD for ``work_items``."""

    def __init__(self, storage_location: str) -> None:
        self.storage_location = storage_location

    @abstractmethod
    def create(
        self,
        work_item_id: str,
        *,
        owner_user_id: str | None,
        title: str,
        description: str | None,
        state: str,
        priority: str,
        project_id: str | None,
        assignee_agent_id: str | None,
        due_at: int | None,
        creator_kind: str = "user",
        created_by_agent_id: str | None = None,
        parent_work_item_id: str | None = None,
        task_kind: str = "general",
        assignee_worker_name: str | None = None,
        delivery_run_id: str | None = None,
        planned_task_id: str | None = None,
        task_key: str | None = None,
        depends_on: tuple[str, ...] = (),
        artifact_requirements: tuple[str, ...] = (),
    ) -> WorkItem: ...

    def get_by_delivery_task(
        self, delivery_run_id: str, task_key: str, *, owner_user_id: str | None
    ) -> WorkItem | None:
        del delivery_run_id, task_key, owner_user_id
        return None

    @abstractmethod
    def get(self, work_item_id: str, *, owner_user_id: str | None) -> WorkItem | None: ...

    @abstractmethod
    def list(self, *, owner_user_id: str | None) -> list[WorkItem]: ...

    @abstractmethod
    def update(
        self,
        work_item_id: str,
        *,
        owner_user_id: str | None,
        expected_version: int,
        changes: dict[str, Any],
    ) -> WorkItem | None: ...
