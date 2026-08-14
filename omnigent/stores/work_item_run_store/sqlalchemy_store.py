"""SQLAlchemy-backed product TaskRun store."""

from __future__ import annotations

import json

from sqlalchemy import desc, func, select

from omnigent.db.db_models import SqlWorkItemRun, current_workspace_id
from omnigent.db.enum_codecs import (
    decode_work_item_run_state,
    decode_work_item_run_trigger,
    encode_work_item_run_state,
    encode_work_item_run_trigger,
)
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.entities import WorkItemRun
from omnigent.stores.work_item_run_store import WorkItemRunStore
from omnigent.work_lifecycle import TaskRunState, TaskRunTrigger

_TERMINAL_STATES = {
    TaskRunState.SUCCEEDED.value,
    TaskRunState.FAILED.value,
    TaskRunState.CANCELLED.value,
}


def _refs(value: str) -> list[str]:
    parsed = json.loads(value)
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _to_entity(row: SqlWorkItemRun) -> WorkItemRun:
    return WorkItemRun(
        id=row.id,
        work_item_id=row.work_item_id,
        owner_user_id=row.owner_user_id,
        session_id=row.session_id,
        agent_id=row.agent_id,
        runtime_id=row.runtime_id,
        workspace=row.workspace,
        state=TaskRunState(decode_work_item_run_state(row.state)),
        trigger=TaskRunTrigger(decode_work_item_run_trigger(row.trigger)),
        retry_of_run_id=row.retry_of_run_id,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        updated_at=row.updated_at,
        result_summary=row.result_summary,
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        failure_retryable=row.failure_retryable,
        artifact_refs=_refs(row.artifact_refs),
        usage_refs=_refs(row.usage_refs),
    )


class SqlAlchemyWorkItemRunStore(WorkItemRunStore):
    """Relational TaskRun history with terminal-state protection."""

    def __init__(self, storage_location: str) -> None:
        super().__init__(storage_location)
        self._engine = get_or_create_engine(storage_location)
        self._session = make_managed_session_maker(self._engine)

    def create(self, run_id: str, **kwargs: object) -> WorkItemRun:
        with self._session() as session:
            work_item_id = str(kwargs["work_item_id"])
            latest = session.scalar(
                select(func.max(SqlWorkItemRun.queued_at)).where(
                    SqlWorkItemRun.workspace_id == current_workspace_id(),
                    SqlWorkItemRun.work_item_id == work_item_id,
                )
            )
            queued_at = max(now_epoch(), int(latest or 0) + 1)
            row = SqlWorkItemRun(
                id=run_id,
                work_item_id=work_item_id,
                owner_user_id=kwargs.get("owner_user_id"),
                session_id=None,
                agent_id=str(kwargs["agent_id"]),
                runtime_id=str(kwargs["runtime_id"]),
                workspace=str(kwargs["workspace"]),
                state=encode_work_item_run_state(TaskRunState.QUEUED.value),
                trigger=encode_work_item_run_trigger(str(kwargs["trigger"])),
                retry_of_run_id=kwargs.get("retry_of_run_id"),
                queued_at=queued_at,
                failure_retryable=False,
                artifact_refs="[]",
                usage_refs="[]",
            )
            session.add(row)
            session.flush()
            return _to_entity(row)

    def get(self, run_id: str, *, owner_user_id: str | None) -> WorkItemRun | None:
        with self._session() as session:
            row = session.get(SqlWorkItemRun, (current_workspace_id(), run_id))
            if row is None or row.owner_user_id != owner_user_id:
                return None
            return _to_entity(row)

    def get_by_session_id(self, session_id: str) -> WorkItemRun | None:
        with self._session() as session:
            row = session.scalar(
                select(SqlWorkItemRun).where(
                    SqlWorkItemRun.workspace_id == current_workspace_id(),
                    SqlWorkItemRun.session_id == session_id,
                )
            )
            return _to_entity(row) if row is not None else None

    def list_for_work_item(
        self, work_item_id: str, *, owner_user_id: str | None
    ) -> list[WorkItemRun]:
        with self._session() as session:
            rows = (
                session.execute(
                    select(SqlWorkItemRun)
                    .where(
                        SqlWorkItemRun.workspace_id == current_workspace_id(),
                        SqlWorkItemRun.owner_user_id == owner_user_id,
                        SqlWorkItemRun.work_item_id == work_item_id,
                    )
                    .order_by(desc(SqlWorkItemRun.queued_at), desc(SqlWorkItemRun.id))
                )
                .scalars()
                .all()
            )
            return [_to_entity(row) for row in rows]

    def bind_session(
        self, run_id: str, *, owner_user_id: str | None, session_id: str
    ) -> WorkItemRun | None:
        with self._session() as session:
            row = session.get(SqlWorkItemRun, (current_workspace_id(), run_id))
            if row is None or row.owner_user_id != owner_user_id:
                return None
            row.session_id = session_id
            row.usage_refs = json.dumps([f"session:{session_id}"])
            row.updated_at = now_epoch()
            session.flush()
            return _to_entity(row)

    def record_result_for_session(
        self,
        session_id: str,
        *,
        result_summary: str | None,
        artifact_refs: list[str],
    ) -> WorkItemRun | None:
        with self._session() as session:
            row = session.scalar(
                select(SqlWorkItemRun).where(
                    SqlWorkItemRun.workspace_id == current_workspace_id(),
                    SqlWorkItemRun.session_id == session_id,
                )
            )
            if row is None:
                return None
            if result_summary is not None:
                row.result_summary = result_summary
            row.artifact_refs = json.dumps(list(dict.fromkeys(artifact_refs)))
            row.updated_at = now_epoch()
            session.flush()
            return _to_entity(row)

    def transition(
        self,
        run_id: str,
        *,
        state: str,
        failure_code: str | None = None,
        failure_message: str | None = None,
        failure_retryable: bool = False,
    ) -> WorkItemRun | None:
        with self._session() as session:
            row = session.get(SqlWorkItemRun, (current_workspace_id(), run_id))
            return self._transition_row(
                session,
                row,
                state=state,
                failure_code=failure_code,
                failure_message=failure_message,
                failure_retryable=failure_retryable,
            )

    def transition_for_session(
        self,
        session_id: str,
        *,
        state: str,
        failure_code: str | None = None,
        failure_message: str | None = None,
        failure_retryable: bool = False,
    ) -> WorkItemRun | None:
        with self._session() as session:
            row = session.scalar(
                select(SqlWorkItemRun).where(
                    SqlWorkItemRun.workspace_id == current_workspace_id(),
                    SqlWorkItemRun.session_id == session_id,
                )
            )
            return self._transition_row(
                session,
                row,
                state=state,
                failure_code=failure_code,
                failure_message=failure_message,
                failure_retryable=failure_retryable,
            )

    @staticmethod
    def _transition_row(
        session: object,
        row: SqlWorkItemRun | None,
        *,
        state: str,
        failure_code: str | None,
        failure_message: str | None,
        failure_retryable: bool,
    ) -> WorkItemRun | None:
        if row is None:
            return None
        current = decode_work_item_run_state(row.state)
        if current in _TERMINAL_STATES:
            return _to_entity(row)
        now = now_epoch()
        row.state = encode_work_item_run_state(state)
        if (
            state in {TaskRunState.RUNNING.value, TaskRunState.WAITING.value}
            and row.started_at is None
        ):
            row.started_at = now
        if state in _TERMINAL_STATES:
            row.finished_at = now
        row.updated_at = now
        if state == TaskRunState.FAILED.value:
            row.failure_code = failure_code
            row.failure_message = failure_message
            row.failure_retryable = failure_retryable
        session.flush()  # type: ignore[attr-defined]
        return _to_entity(row)
