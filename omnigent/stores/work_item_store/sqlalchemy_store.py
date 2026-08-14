"""SQLAlchemy-backed product Task store."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import desc, select

from omnigent.db.db_models import SqlWorkItem, current_workspace_id
from omnigent.db.enum_codecs import (
    decode_work_item_creator_kind,
    decode_work_item_priority,
    decode_work_item_state,
    encode_work_item_creator_kind,
    encode_work_item_priority,
    encode_work_item_state,
)
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.entities import WorkItem
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.stores.work_item_store import WorkItemStore
from omnigent.work_lifecycle import TaskState


def _to_entity(row: SqlWorkItem) -> WorkItem:
    return WorkItem(
        id=row.id,
        owner_user_id=row.owner_user_id,
        title=row.title,
        description=row.description,
        state=TaskState(decode_work_item_state(row.state)),
        priority=decode_work_item_priority(row.priority),
        project_id=row.project_id,
        assignee_agent_id=row.assignee_agent_id,
        due_at=row.due_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        version=row.version,
        completion_id=row.completion_id,
        creator_kind=decode_work_item_creator_kind(row.creator_kind),
        created_by_agent_id=row.created_by_agent_id,
        parent_work_item_id=row.parent_work_item_id,
        task_kind=row.task_kind,
        assignee_worker_name=row.assignee_worker_name,
        delivery_run_id=row.delivery_run_id,
        planned_task_id=row.planned_task_id,
        task_key=row.task_key,
        depends_on=tuple(json.loads(row.depends_on)),
        artifact_requirements=tuple(json.loads(row.artifact_requirements)),
    )


class SqlAlchemyWorkItemStore(WorkItemStore):
    """Relational WorkItem persistence with optimistic version checks."""

    def __init__(self, storage_location: str) -> None:
        super().__init__(storage_location)
        self._engine = get_or_create_engine(storage_location)
        self._session = make_managed_session_maker(self._engine)

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
    ) -> WorkItem:
        now = now_epoch()
        state_code = encode_work_item_state(state)
        row = SqlWorkItem(
            id=work_item_id,
            owner_user_id=owner_user_id,
            title=title,
            description=description,
            state=state_code,
            priority=encode_work_item_priority(priority),
            project_id=project_id,
            assignee_agent_id=assignee_agent_id,
            due_at=due_at,
            created_at=now,
            updated_at=None,
            completed_at=now if state == TaskState.DONE.value else None,
            completion_id=uuid.uuid4().hex if state == TaskState.DONE.value else None,
            creator_kind=encode_work_item_creator_kind(creator_kind),
            created_by_agent_id=created_by_agent_id,
            parent_work_item_id=parent_work_item_id,
            task_kind=task_kind,
            assignee_worker_name=assignee_worker_name,
            delivery_run_id=delivery_run_id,
            planned_task_id=planned_task_id,
            task_key=task_key,
            depends_on=json.dumps(depends_on),
            artifact_requirements=json.dumps(artifact_requirements),
            version=1,
        )
        with self._session() as session:
            session.add(row)
            session.flush()
            return _to_entity(row)

    def get_by_delivery_task(
        self, delivery_run_id: str, task_key: str, *, owner_user_id: str | None
    ) -> WorkItem | None:
        with self._session() as session:
            row = session.execute(
                select(SqlWorkItem).where(
                    SqlWorkItem.workspace_id == current_workspace_id(),
                    SqlWorkItem.owner_user_id == owner_user_id,
                    SqlWorkItem.delivery_run_id == delivery_run_id,
                    SqlWorkItem.task_key == task_key,
                )
            ).scalar_one_or_none()
            return _to_entity(row) if row is not None else None

    def get(self, work_item_id: str, *, owner_user_id: str | None) -> WorkItem | None:
        with self._session() as session:
            row = session.get(SqlWorkItem, (current_workspace_id(), work_item_id))
            if row is None or row.owner_user_id != owner_user_id:
                return None
            return _to_entity(row)

    def list(self, *, owner_user_id: str | None) -> list[WorkItem]:
        with self._session() as session:
            rows = (
                session.execute(
                    select(SqlWorkItem)
                    .where(
                        SqlWorkItem.workspace_id == current_workspace_id(),
                        SqlWorkItem.owner_user_id == owner_user_id,
                    )
                    .order_by(
                        desc(SqlWorkItem.updated_at),
                        desc(SqlWorkItem.created_at),
                        desc(SqlWorkItem.id),
                    )
                )
                .scalars()
                .all()
            )
            return [_to_entity(row) for row in rows]

    def update(
        self,
        work_item_id: str,
        *,
        owner_user_id: str | None,
        expected_version: int,
        changes: dict[str, Any],
    ) -> WorkItem | None:
        with self._session() as session:
            row = session.get(SqlWorkItem, (current_workspace_id(), work_item_id))
            if row is None or row.owner_user_id != owner_user_id:
                return None
            if row.version != expected_version:
                raise OmnigentError(
                    f"Task changed since version {expected_version}",
                    code=ErrorCode.CONFLICT,
                )

            encoded = dict(changes)
            if "state" in encoded:
                state = str(encoded.pop("state"))
                was_done = decode_work_item_state(row.state) == TaskState.DONE.value
                row.state = encode_work_item_state(state)
                if state == TaskState.DONE.value:
                    if not was_done:
                        row.completed_at = now_epoch()
                        row.completion_id = uuid.uuid4().hex
                else:
                    row.completed_at = None
                    row.completion_id = None
            if "priority" in encoded:
                row.priority = encode_work_item_priority(str(encoded.pop("priority")))
            for key, value in encoded.items():
                if key in {"depends_on", "artifact_requirements"}:
                    value = json.dumps(value)
                setattr(row, key, value)

            if changes:
                row.updated_at = now_epoch()
                row.version += 1
            session.flush()
            return _to_entity(row)
