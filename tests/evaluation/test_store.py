from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, text

from omnigent.db.db_models import workspace_scope
from omnigent.db.utils import get_or_create_engine


def _modules() -> tuple[Any, Any]:
    try:
        entities = importlib.import_module("omnigent.entities.run_evaluation")
        store = importlib.import_module("omnigent.stores.evaluation_store.sqlalchemy_store")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Evaluation persistence is missing: {exc}")
    return entities, store


def _record(entities: Any, *, owner: str = "alice") -> Any:
    metrics = entities.EvaluationMetrics(
        task_completion_rate=1.0,
        attempt_success_rate=1.0,
        retry_count=0,
        blocked_count=0,
        blocked_duration_seconds=0,
        parallel_overlap_seconds=5,
        max_concurrency=2,
        worker_duration_seconds=20,
        parent_inbox_latency_seconds=2.0,
        parent_inbox_latency_samples=1,
        failure_categories={},
        evidence_counts=entities.EvidenceCounts(session=3),
    )
    return entities.EvaluationRecord(
        id="a" * 32,
        run_id="1" * 32,
        owner_user_id=owner,
        evaluator="session-collaboration",
        version=1,
        status=entities.EvaluationStatus.FINAL,
        metrics=metrics,
        workers=(),
        evidence_refs=("session:root", "event:test-1"),
        rubric=None,
        created_at=10,
        updated_at=10,
    )


def test_store_is_idempotent_workspace_and_owner_scoped(tmp_path: Path) -> None:
    entities, stores = _modules()
    database = f"sqlite:///{tmp_path / 'evaluations.db'}"
    store = stores.SqlAlchemyEvaluationStore(database)
    first = _record(entities)

    with workspace_scope(11):
        assert store.upsert(first) == first
        updated = store.upsert(
            entities.EvaluationRecord(
                **{
                    **first.__dict__,
                    "status": entities.EvaluationStatus.PREVIEW,
                    "updated_at": 20,
                }
            )
        )
        assert updated.id == first.id
        assert updated.created_at == first.created_at
        assert updated.updated_at == 20
        assert (
            store.get(
                run_id=first.run_id,
                evaluator=first.evaluator,
                version=first.version,
                owner_user_id="mallory",
            )
            is None
        )

    with workspace_scope(12):
        assert (
            store.get(
                run_id=first.run_id,
                evaluator=first.evaluator,
                version=first.version,
                owner_user_id="alice",
            )
            is None
        )

    with workspace_scope(11):
        loaded = store.get(
            run_id=first.run_id,
            evaluator=first.evaluator,
            version=first.version,
            owner_user_id="alice",
        )
        assert loaded is not None
        assert loaded.status is entities.EvaluationStatus.PREVIEW


def test_schema_and_blobs_never_store_transcript_prompt_or_secret(tmp_path: Path) -> None:
    entities, stores = _modules()
    database = f"sqlite:///{tmp_path / 'safe-evaluations.db'}"
    store = stores.SqlAlchemyEvaluationStore(database)
    record = _record(entities)
    store.upsert(record)

    engine = get_or_create_engine(database)
    columns = {column["name"] for column in inspect(engine).get_columns("run_evaluations")}
    forbidden = {"transcript", "prompt", "messages", "secret", "payload"}
    assert columns.isdisjoint(forbidden)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT metrics, evidence_refs FROM run_evaluations")).one()
    serialized = json.dumps(list(row))
    assert "transcript" not in serialized
    assert "prompt" not in serialized
    assert "secret" not in serialized
