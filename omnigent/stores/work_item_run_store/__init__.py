"""Persistence contract for product TaskRun history."""

from __future__ import annotations

from abc import ABC, abstractmethod

from omnigent.entities import WorkItemRun


class WorkItemRunStore(ABC):
    """Owner-scoped TaskRun persistence and Session status projection."""

    def __init__(self, storage_location: str) -> None:
        self.storage_location = storage_location

    @abstractmethod
    def create(self, run_id: str, **kwargs: object) -> WorkItemRun: ...

    @abstractmethod
    def get(self, run_id: str, *, owner_user_id: str | None) -> WorkItemRun | None: ...

    def get_by_session_id(self, session_id: str) -> WorkItemRun | None:
        del session_id
        return None

    @abstractmethod
    def list_for_work_item(
        self, work_item_id: str, *, owner_user_id: str | None
    ) -> list[WorkItemRun]: ...

    @abstractmethod
    def bind_session(
        self, run_id: str, *, owner_user_id: str | None, session_id: str
    ) -> WorkItemRun | None: ...

    @abstractmethod
    def record_result_for_session(
        self,
        session_id: str,
        *,
        result_summary: str | None,
        artifact_refs: list[str],
    ) -> WorkItemRun | None: ...

    @abstractmethod
    def transition(
        self,
        run_id: str,
        *,
        state: str,
        failure_code: str | None = None,
        failure_message: str | None = None,
        failure_retryable: bool = False,
    ) -> WorkItemRun | None: ...

    @abstractmethod
    def transition_for_session(
        self,
        session_id: str,
        *,
        state: str,
        failure_code: str | None = None,
        failure_message: str | None = None,
        failure_retryable: bool = False,
    ) -> WorkItemRun | None: ...
