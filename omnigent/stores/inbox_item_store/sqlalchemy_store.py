"""SQLAlchemy-backed persistent Inbox store."""

from __future__ import annotations

from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError

from omnigent.db.db_models import SqlInboxItem, current_workspace_id
from omnigent.db.enum_codecs import decode_inbox_item_kind, encode_inbox_item_kind
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.entities import InboxItem, InboxItemKind
from omnigent.stores.inbox_item_store import InboxItemStore


def _to_entity(row: SqlInboxItem) -> InboxItem:
    return InboxItem(
        id=row.id,
        owner_user_id=row.owner_user_id,
        kind=InboxItemKind(decode_inbox_item_kind(row.kind)),
        dedupe_key=row.dedupe_key,
        work_item_id=row.work_item_id,
        work_item_run_id=row.work_item_run_id,
        session_id=row.session_id,
        source_id=row.source_id,
        message=row.message,
        target_url=row.target_url,
        action_required=row.action_required,
        created_at=row.created_at,
        updated_at=row.updated_at,
        read_at=row.read_at,
        resolved_at=row.resolved_at,
    )


class SqlAlchemyInboxItemStore(InboxItemStore):
    """Relational Inbox storage with database-enforced event deduplication."""

    def __init__(self, storage_location: str) -> None:
        super().__init__(storage_location)
        self._engine = get_or_create_engine(storage_location)
        self._session = make_managed_session_maker(self._engine)

    def create_if_absent(self, item_id: str, **kwargs: object) -> tuple[InboxItem, bool]:
        row = SqlInboxItem(
            id=item_id,
            owner_user_id=kwargs.get("owner_user_id"),
            kind=encode_inbox_item_kind(str(kwargs["kind"])),
            dedupe_key=str(kwargs["dedupe_key"]),
            work_item_id=kwargs.get("work_item_id"),
            work_item_run_id=kwargs.get("work_item_run_id"),
            session_id=kwargs.get("session_id"),
            source_id=kwargs.get("source_id"),
            message=kwargs.get("message"),
            target_url=str(kwargs["target_url"]),
            action_required=bool(kwargs.get("action_required", False)),
            created_at=now_epoch(),
        )
        try:
            with self._session() as session:
                session.add(row)
                session.flush()
                return _to_entity(row), True
        except IntegrityError:
            with self._session() as session:
                existing = session.scalar(
                    select(SqlInboxItem).where(
                        SqlInboxItem.workspace_id == current_workspace_id(),
                        SqlInboxItem.dedupe_key == str(kwargs["dedupe_key"]),
                    )
                )
                if existing is None:
                    raise
                return _to_entity(existing), False

    def list(
        self, *, owner_user_id: str | None, unread_only: bool = False, limit: int = 100
    ) -> list[InboxItem]:
        where = [
            SqlInboxItem.workspace_id == current_workspace_id(),
            SqlInboxItem.owner_user_id == owner_user_id,
        ]
        if unread_only:
            where.append(SqlInboxItem.read_at.is_(None))
        with self._session() as session:
            rows = (
                session.execute(
                    select(SqlInboxItem)
                    .where(*where)
                    .order_by(desc(SqlInboxItem.created_at), desc(SqlInboxItem.id))
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_to_entity(row) for row in rows]

    def count_unread(self, *, owner_user_id: str | None) -> int:
        with self._session() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(SqlInboxItem)
                    .where(
                        SqlInboxItem.workspace_id == current_workspace_id(),
                        SqlInboxItem.owner_user_id == owner_user_id,
                        SqlInboxItem.read_at.is_(None),
                    )
                )
                or 0
            )

    def set_read(self, item_id: str, *, owner_user_id: str | None, read: bool) -> InboxItem | None:
        with self._session() as session:
            row = session.get(SqlInboxItem, (current_workspace_id(), item_id))
            if row is None or row.owner_user_id != owner_user_id:
                return None
            row.read_at = now_epoch() if read else None
            row.updated_at = now_epoch()
            session.flush()
            return _to_entity(row)

    def mark_all_read(self, *, owner_user_id: str | None) -> int:
        now = now_epoch()
        with self._session() as session:
            result = session.execute(
                update(SqlInboxItem)
                .where(
                    SqlInboxItem.workspace_id == current_workspace_id(),
                    SqlInboxItem.owner_user_id == owner_user_id,
                    SqlInboxItem.read_at.is_(None),
                )
                .values(read_at=now, updated_at=now)
            )
            return int(result.rowcount or 0)

    def has_task_completion(self, work_item_id: str, *, owner_user_id: str | None) -> bool:
        with self._session() as session:
            return (
                session.scalar(
                    select(SqlInboxItem.id)
                    .where(
                        SqlInboxItem.workspace_id == current_workspace_id(),
                        SqlInboxItem.owner_user_id == owner_user_id,
                        SqlInboxItem.work_item_id == work_item_id,
                        SqlInboxItem.kind == encode_inbox_item_kind("task_completed"),
                    )
                    .limit(1)
                )
                is not None
            )

    def resolve(self, dedupe_key: str) -> InboxItem | None:
        with self._session() as session:
            row = session.scalar(
                select(SqlInboxItem).where(
                    SqlInboxItem.workspace_id == current_workspace_id(),
                    SqlInboxItem.dedupe_key == dedupe_key,
                )
            )
            if row is None:
                return None
            now = now_epoch()
            row.action_required = False
            row.resolved_at = now
            row.updated_at = now
            session.flush()
            return _to_entity(row)
