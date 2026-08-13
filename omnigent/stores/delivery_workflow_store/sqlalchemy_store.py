"""SQLAlchemy persistence for development-delivery workflows."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from omnigent.db.db_models import (
    SqlDeliveryArtifact,
    SqlDeliveryPlannedTask,
    SqlDeliveryRun,
    SqlDeliveryTransition,
    current_workspace_id,
)
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.entities.delivery_workflow import (
    DeliveryArtifact,
    DeliveryPhase,
    DeliveryRun,
    DeliveryStatus,
    DeliveryTransition,
    DeliveryWorkflowSnapshot,
    PlannedTask,
    PlannedTaskStatus,
)
from omnigent.errors import ErrorCode, OmnigentError


class SqlAlchemyDeliveryWorkflowStore:
    """One transactional boundary for plan, evidence, and transitions."""

    def __init__(self, storage_location: str) -> None:
        self.storage_location = storage_location
        self._session = make_managed_session_maker(get_or_create_engine(storage_location))

    def get(
        self,
        runtime_run_id: str,
        *,
        profile_id: str,
        owner_user_id: str,
    ) -> DeliveryWorkflowSnapshot | None:
        with self._session() as session:
            row = self._find_run(session, runtime_run_id, profile_id, owner_user_id)
            if row is None:
                return None
            return self._snapshot(session, row)

    def put_plan(
        self,
        runtime_run_id: str,
        *,
        profile_id: str,
        owner_user_id: str,
        expected_version: int,
        tasks: Iterable[Mapping[str, Any]],
    ) -> DeliveryWorkflowSnapshot:
        task_specs = tuple(tasks)
        now = now_epoch()
        with self._session() as session:
            row = self._find_run(session, runtime_run_id, profile_id, owner_user_id)
            if row is None:
                if expected_version != 0:
                    raise OmnigentError(
                        "Delivery workflow version conflict",
                        code=ErrorCode.CONFLICT,
                    )
                row = SqlDeliveryRun(
                    id=uuid4().hex,
                    runtime_run_id=runtime_run_id,
                    profile_id=profile_id,
                    owner_user_id=owner_user_id,
                    phase=DeliveryPhase.INTAKE.value,
                    status=DeliveryStatus.ACTIVE.value,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                try:
                    session.flush()
                except IntegrityError as exc:
                    raise OmnigentError(
                        "Delivery workflow was initialized concurrently",
                        code=ErrorCode.CONFLICT,
                    ) from exc
            else:
                if row.version != expected_version:
                    raise OmnigentError(
                        "Delivery workflow version conflict",
                        code=ErrorCode.CONFLICT,
                    )
                row.version += 1
                row.updated_at = now
                session.execute(
                    delete(SqlDeliveryPlannedTask).where(
                        SqlDeliveryPlannedTask.workspace_id == current_workspace_id(),
                        SqlDeliveryPlannedTask.delivery_run_id == row.id,
                    )
                )
            for spec in task_specs:
                session.add(
                    SqlDeliveryPlannedTask(
                        id=uuid4().hex,
                        delivery_run_id=row.id,
                        task_key=str(spec["task_key"]),
                        title=str(spec["title"]),
                        owner_role=str(spec["owner_role"]),
                        status=PlannedTaskStatus.PLANNED.value,
                        depends_on=_dump(tuple(spec.get("depends_on", ()))),
                        artifact_requirements=_dump(
                            tuple(spec.get("artifact_requirements", ()))
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                )
            try:
                session.flush()
            except IntegrityError as exc:
                raise OmnigentError(
                    "Delivery plan contains duplicate task keys",
                    code=ErrorCode.CONFLICT,
                ) from exc
            return self._snapshot(session, row)

    def add_artifact(
        self,
        runtime_run_id: str,
        *,
        profile_id: str,
        owner_user_id: str,
        kind: str,
        location: str,
        content_sha256: str,
        planned_task_id: str | None,
        metadata: Mapping[str, Any],
    ) -> DeliveryArtifact:
        with self._session() as session:
            run = self._require_run(session, runtime_run_id, profile_id, owner_user_id)
            if planned_task_id is not None:
                task = session.get(
                    SqlDeliveryPlannedTask,
                    (current_workspace_id(), planned_task_id),
                )
                if task is None or task.delivery_run_id != run.id:
                    raise OmnigentError(
                        "Planned task does not belong to this delivery workflow",
                        code=ErrorCode.INVALID_INPUT,
                    )
            row = SqlDeliveryArtifact(
                id=uuid4().hex,
                delivery_run_id=run.id,
                planned_task_id=planned_task_id,
                kind=kind,
                location=location,
                content_sha256=content_sha256,
                metadata_json=_dump(dict(metadata)),
                created_at=now_epoch(),
            )
            session.add(row)
            session.flush()
            return _artifact(row)

    def transition(
        self,
        runtime_run_id: str,
        *,
        profile_id: str,
        owner_user_id: str,
        actor_id: str,
        expected_phase: DeliveryPhase,
        expected_version: int,
        to_phase: DeliveryPhase,
        to_status: DeliveryStatus,
        idempotency_key: str,
        evidence_refs: Iterable[str],
        validate: Callable[[DeliveryRun], None],
    ) -> DeliveryWorkflowSnapshot:
        evidence = tuple(evidence_refs)
        with self._session() as session:
            run = self._require_run(session, runtime_run_id, profile_id, owner_user_id)
            existing = session.execute(
                select(SqlDeliveryTransition).where(
                    SqlDeliveryTransition.workspace_id == current_workspace_id(),
                    SqlDeliveryTransition.profile_id == profile_id,
                    SqlDeliveryTransition.delivery_run_id == run.id,
                    SqlDeliveryTransition.idempotency_key == idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                if not _same_transition_request(
                    existing,
                    expected_phase=expected_phase,
                    expected_version=expected_version,
                    to_phase=to_phase,
                    to_status=to_status,
                    evidence_refs=evidence,
                ):
                    raise OmnigentError(
                        "Idempotency key was already used for another transition",
                        code=ErrorCode.CONFLICT,
                    )
                return self._snapshot(session, run)
            validate(_run(run))
            if run.phase != expected_phase.value or run.version != expected_version:
                raise OmnigentError(
                    "Delivery workflow version or phase conflict",
                    code=ErrorCode.CONFLICT,
                )
            artifacts = tuple(
                session.execute(
                    select(SqlDeliveryArtifact).where(
                        SqlDeliveryArtifact.workspace_id == current_workspace_id(),
                        SqlDeliveryArtifact.id.in_(evidence),
                    )
                ).scalars()
            )
            if len(artifacts) != len(set(evidence)) or any(
                artifact.delivery_run_id != run.id for artifact in artifacts
            ):
                raise OmnigentError(
                    "Every evidence reference must be registered for this delivery workflow",
                    code=ErrorCode.INVALID_INPUT,
                )
            now = now_epoch()
            result_version = expected_version + 1
            result = session.execute(
                update(SqlDeliveryRun)
                .where(
                    SqlDeliveryRun.workspace_id == current_workspace_id(),
                    SqlDeliveryRun.id == run.id,
                    SqlDeliveryRun.profile_id == profile_id,
                    SqlDeliveryRun.owner_user_id == owner_user_id,
                    SqlDeliveryRun.phase == expected_phase.value,
                    SqlDeliveryRun.version == expected_version,
                )
                .values(
                    phase=to_phase.value,
                    status=to_status.value,
                    version=result_version,
                    updated_at=now,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise OmnigentError("Delivery workflow version conflict", code=ErrorCode.CONFLICT)
            transition = SqlDeliveryTransition(
                id=uuid4().hex,
                delivery_run_id=run.id,
                profile_id=profile_id,
                idempotency_key=idempotency_key,
                from_phase=expected_phase.value,
                to_phase=to_phase.value,
                from_status=run.status,
                to_status=to_status.value,
                expected_version=expected_version,
                result_version=result_version,
                evidence_refs=_dump(evidence),
                actor_id=actor_id,
                created_at=now,
            )
            session.add(transition)
            session.flush()
            session.refresh(run)
            return self._snapshot(session, run)

    @staticmethod
    def _find_run(
        session: Any,
        runtime_run_id: str,
        profile_id: str,
        owner_user_id: str,
    ) -> SqlDeliveryRun | None:
        return cast(
            SqlDeliveryRun | None,
            session.execute(
                select(SqlDeliveryRun).where(
                    SqlDeliveryRun.workspace_id == current_workspace_id(),
                    SqlDeliveryRun.runtime_run_id == runtime_run_id,
                    SqlDeliveryRun.profile_id == profile_id,
                    SqlDeliveryRun.owner_user_id == owner_user_id,
                )
            ).scalar_one_or_none(),
        )

    def _require_run(
        self,
        session: Any,
        runtime_run_id: str,
        profile_id: str,
        owner_user_id: str,
    ) -> SqlDeliveryRun:
        row = self._find_run(session, runtime_run_id, profile_id, owner_user_id)
        if row is None:
            raise OmnigentError("Delivery workflow not found", code=ErrorCode.NOT_FOUND)
        return row

    @staticmethod
    def _snapshot(session: Any, row: SqlDeliveryRun) -> DeliveryWorkflowSnapshot:
        tasks = tuple(
            _task(item)
            for item in session.execute(
                select(SqlDeliveryPlannedTask)
                .where(
                    SqlDeliveryPlannedTask.workspace_id == current_workspace_id(),
                    SqlDeliveryPlannedTask.delivery_run_id == row.id,
                )
                .order_by(SqlDeliveryPlannedTask.task_key, SqlDeliveryPlannedTask.id)
            ).scalars()
        )
        artifacts = tuple(
            _artifact(item)
            for item in session.execute(
                select(SqlDeliveryArtifact)
                .where(
                    SqlDeliveryArtifact.workspace_id == current_workspace_id(),
                    SqlDeliveryArtifact.delivery_run_id == row.id,
                )
                .order_by(SqlDeliveryArtifact.created_at, SqlDeliveryArtifact.id)
            ).scalars()
        )
        transitions = tuple(
            _transition(item)
            for item in session.execute(
                select(SqlDeliveryTransition)
                .where(
                    SqlDeliveryTransition.workspace_id == current_workspace_id(),
                    SqlDeliveryTransition.delivery_run_id == row.id,
                )
                .order_by(SqlDeliveryTransition.result_version, SqlDeliveryTransition.id)
            ).scalars()
        )
        return DeliveryWorkflowSnapshot(_run(row), tasks, artifacts, transitions)


def _dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _load(value: str) -> Any:
    return json.loads(value)


def _run(row: SqlDeliveryRun) -> DeliveryRun:
    return DeliveryRun(
        id=row.id,
        runtime_run_id=row.runtime_run_id,
        profile_id=row.profile_id,
        owner_user_id=row.owner_user_id,
        phase=DeliveryPhase(row.phase),
        status=DeliveryStatus(row.status),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _task(row: SqlDeliveryPlannedTask) -> PlannedTask:
    return PlannedTask(
        id=row.id,
        delivery_run_id=row.delivery_run_id,
        task_key=row.task_key,
        title=row.title,
        owner_role=row.owner_role,
        status=PlannedTaskStatus(row.status),
        depends_on=tuple(_load(row.depends_on)),
        artifact_requirements=tuple(_load(row.artifact_requirements)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _artifact(row: SqlDeliveryArtifact) -> DeliveryArtifact:
    return DeliveryArtifact(
        id=row.id,
        delivery_run_id=row.delivery_run_id,
        planned_task_id=row.planned_task_id,
        kind=row.kind,
        location=row.location,
        content_sha256=row.content_sha256,
        metadata=dict(_load(row.metadata_json)),
        created_at=row.created_at,
    )


def _transition(row: SqlDeliveryTransition) -> DeliveryTransition:
    return DeliveryTransition(
        id=row.id,
        delivery_run_id=row.delivery_run_id,
        profile_id=row.profile_id,
        idempotency_key=row.idempotency_key,
        from_phase=DeliveryPhase(row.from_phase),
        to_phase=DeliveryPhase(row.to_phase),
        from_status=DeliveryStatus(row.from_status),
        to_status=DeliveryStatus(row.to_status),
        expected_version=row.expected_version,
        result_version=row.result_version,
        evidence_refs=tuple(_load(row.evidence_refs)),
        actor_id=row.actor_id,
        created_at=row.created_at,
    )


def _same_transition_request(
    row: SqlDeliveryTransition,
    *,
    expected_phase: DeliveryPhase,
    expected_version: int,
    to_phase: DeliveryPhase,
    to_status: DeliveryStatus,
    evidence_refs: tuple[str, ...],
) -> bool:
    return (
        row.from_phase == expected_phase.value
        and row.expected_version == expected_version
        and row.to_phase == to_phase.value
        and row.to_status == to_status.value
        and tuple(_load(row.evidence_refs)) == evidence_refs
    )
