"""SQLAlchemy persistence for deterministic Run evaluations."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import select

from omnigent.db.db_models import SqlRunEvaluation, current_workspace_id
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker
from omnigent.entities.run_evaluation import (
    EvaluationMetrics,
    EvaluationRecord,
    EvaluationStatus,
    EvidenceCounts,
    WorkerEvaluation,
)
from omnigent.stores.evaluation_store import EvaluationStore


class SqlAlchemyEvaluationStore(EvaluationStore):
    """Durable store with ambient workspace and explicit owner isolation."""

    def __init__(self, storage_location: str) -> None:
        super().__init__(storage_location)
        self._session = make_managed_session_maker(get_or_create_engine(storage_location))

    def get(
        self,
        *,
        run_id: str,
        evaluator: str,
        version: int,
        owner_user_id: str,
    ) -> EvaluationRecord | None:
        with self._session() as session:
            row = session.execute(
                select(SqlRunEvaluation).where(
                    SqlRunEvaluation.workspace_id == current_workspace_id(),
                    SqlRunEvaluation.run_id == run_id,
                    SqlRunEvaluation.evaluator == evaluator,
                    SqlRunEvaluation.version == version,
                    SqlRunEvaluation.owner_user_id == owner_user_id,
                )
            ).scalar_one_or_none()
            return _record(row) if row is not None else None

    def upsert(self, record: EvaluationRecord) -> EvaluationRecord:
        metrics = _encode_metrics(record)
        evidence_refs = json.dumps(record.evidence_refs, separators=(",", ":"))
        with self._session() as session:
            row = session.execute(
                select(SqlRunEvaluation).where(
                    SqlRunEvaluation.workspace_id == current_workspace_id(),
                    SqlRunEvaluation.run_id == record.run_id,
                    SqlRunEvaluation.evaluator == record.evaluator,
                    SqlRunEvaluation.version == record.version,
                )
            ).scalar_one_or_none()
            if row is None:
                row = SqlRunEvaluation(
                    id=record.id,
                    run_id=record.run_id,
                    owner_user_id=record.owner_user_id,
                    evaluator=record.evaluator,
                    version=record.version,
                    status=record.status.value,
                    metrics=metrics,
                    evidence_refs=evidence_refs,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
                session.add(row)
            else:
                if row.owner_user_id != record.owner_user_id:
                    raise ValueError("Run evaluation belongs to another owner")
                row.status = record.status.value
                row.metrics = metrics
                row.evidence_refs = evidence_refs
                row.updated_at = record.updated_at
            session.flush()
            return _record(row)


def _encode_metrics(record: EvaluationRecord) -> str:
    payload = {
        "collaboration": asdict(record.metrics),
        "workers": [asdict(worker) for worker in record.workers],
        "rubric": record.rubric,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _record(row: SqlRunEvaluation) -> EvaluationRecord:
    payload: dict[str, Any] = json.loads(row.metrics)
    collaboration = dict(payload["collaboration"])
    evidence_counts = EvidenceCounts(**collaboration.pop("evidence_counts"))
    metrics = EvaluationMetrics(**collaboration, evidence_counts=evidence_counts)
    workers = tuple(WorkerEvaluation(**worker) for worker in payload.get("workers", ()))
    return EvaluationRecord(
        id=row.id,
        run_id=row.run_id,
        owner_user_id=row.owner_user_id,
        evaluator=row.evaluator,
        version=row.version,
        status=EvaluationStatus(row.status),
        metrics=metrics,
        workers=workers,
        evidence_refs=tuple(json.loads(row.evidence_refs)),
        rubric=payload.get("rubric"),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
