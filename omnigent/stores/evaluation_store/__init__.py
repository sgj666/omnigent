"""Persistence contract for versioned Run evaluation records."""

from __future__ import annotations

from abc import ABC, abstractmethod

from omnigent.entities.run_evaluation import EvaluationRecord


class EvaluationStore(ABC):
    """Owner- and workspace-scoped evaluation persistence."""

    def __init__(self, storage_location: str) -> None:
        self.storage_location = storage_location

    @abstractmethod
    def get(
        self,
        *,
        run_id: str,
        evaluator: str,
        version: int,
        owner_user_id: str,
    ) -> EvaluationRecord | None:
        """Return one owned evaluator version, or ``None``."""

    @abstractmethod
    def upsert(self, record: EvaluationRecord) -> EvaluationRecord:
        """Insert or refresh the same Run/evaluator/version record."""


from omnigent.stores.evaluation_store.sqlalchemy_store import (  # noqa: E402
    SqlAlchemyEvaluationStore,
)

__all__ = ["EvaluationStore", "SqlAlchemyEvaluationStore"]
