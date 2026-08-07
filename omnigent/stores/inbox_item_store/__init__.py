"""Persistence contract for product Inbox items."""

from __future__ import annotations

from abc import ABC, abstractmethod

from omnigent.entities import InboxItem


class InboxItemStore(ABC):
    """Owner-scoped durable Inbox persistence."""

    def __init__(self, storage_location: str) -> None:
        self.storage_location = storage_location

    @abstractmethod
    def create_if_absent(self, item_id: str, **kwargs: object) -> tuple[InboxItem, bool]: ...

    @abstractmethod
    def list(
        self, *, owner_user_id: str | None, unread_only: bool = False, limit: int = 100
    ) -> list[InboxItem]: ...

    @abstractmethod
    def count_unread(self, *, owner_user_id: str | None) -> int: ...

    @abstractmethod
    def set_read(
        self, item_id: str, *, owner_user_id: str | None, read: bool
    ) -> InboxItem | None: ...

    @abstractmethod
    def mark_all_read(self, *, owner_user_id: str | None) -> int: ...

    @abstractmethod
    def has_task_completion(self, work_item_id: str, *, owner_user_id: str | None) -> bool: ...

    @abstractmethod
    def resolve(self, dedupe_key: str) -> InboxItem | None: ...
