"""Durable idempotency and ledger storage adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from omnigent.db.db_models import SqlHarnessEvent, SqlIdempotencyKey
from omnigent.teams.events import ActorType, EventType, LedgerEvent, LedgerStore


@dataclass(frozen=True)
class IdempotencyKey:
    """The unique ``(scope, event_id)`` identity persisted for an event."""

    scope: str
    event_id: str


class IdempotencyRegistry:
    """Compatibility adapter useful for pure replay tests.

    Production callers should use :class:`SqlAlchemyLedgerStore`, which stores
    the same identity in ``idempotency_keys`` transactionally.
    """

    def __init__(self) -> None:
        self._keys: set[IdempotencyKey] = set()

    def claim(self, scope: str, event_id: str) -> bool:
        """Record an event identity, returning false when it was already seen."""

        key = IdempotencyKey(scope=scope, event_id=event_id)
        if key in self._keys:
            return False
        self._keys.add(key)
        return True


def _encode_event(event: LedgerEvent) -> str:
    """Encode all event metadata, including fields absent from Task 2 columns."""

    return json.dumps(
        {
            "event_id": event.event_id,
            "actor_type": event.actor_type.value,
            "actor_id": event.actor_id,
            "correlation_id": event.correlation_id,
            "payload": event.payload,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_event(row: SqlHarnessEvent) -> LedgerEvent:
    envelope = json.loads(row.payload or "{}")
    return LedgerEvent(
        event_id=envelope.get("event_id", row.event_id),
        run_id=row.run_id or "",
        event_type=EventType(row.event_type),
        actor_type=ActorType(envelope["actor_type"]),
        actor_id=envelope["actor_id"],
        occurred_at=row.created_at,
        payload=envelope.get("payload", {}),
        correlation_id=envelope.get("correlation_id"),
    )


class SqlAlchemyLedgerStore(LedgerStore):
    """Append/replay events using the existing workspace-scoped tables."""

    def __init__(self, session: Session, workspace_id: int) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def append(self, scope: str, event: LedgerEvent) -> bool:
        """Atomically claim and append an event; duplicate claims are no-ops."""

        storage_event_id = _storage_event_id(scope, event.event_id)
        last_error: IntegrityError | None = None
        for _attempt in range(3):
            try:
                with self._session.begin_nested():
                    self._session.add(
                        SqlIdempotencyKey(
                            workspace_id=self._workspace_id,
                            id=uuid4().hex,
                            scope=scope,
                            key=event.event_id,
                            created_at=event.occurred_at,
                        )
                    )
                    self._session.flush()
                    self._session.add(
                        SqlHarnessEvent(
                            workspace_id=self._workspace_id,
                            id=uuid4().hex,
                            event_id=storage_event_id,
                            sequence=self._next_sequence(),
                            run_id=event.run_id,
                            event_type=event.event_type.value,
                            payload=_encode_event(event),
                            created_at=event.occurred_at,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                if self._has_claim(scope, event.event_id):
                    return False
                last_error = exc
                continue
            return True
        assert last_error is not None
        raise last_error

    def _has_claim(self, scope: str, event_id: str) -> bool:
        return (
            self._session.query(SqlIdempotencyKey.id)
            .filter(
                SqlIdempotencyKey.workspace_id == self._workspace_id,
                SqlIdempotencyKey.scope == scope,
                SqlIdempotencyKey.key == event_id,
            )
            .first()
            is not None
        )

    def _next_sequence(self) -> int:
        """Allocate the next workspace-local durable ordering value."""

        latest = (
            self._session.query(SqlHarnessEvent.sequence)
            .filter(SqlHarnessEvent.workspace_id == self._workspace_id)
            .order_by(SqlHarnessEvent.sequence.desc())
            .first()
        )
        return (latest[0] if latest is not None else 0) + 1

    def list_events(self, scope: str, run_id: str) -> Sequence[LedgerEvent]:
        """Replay events for this workspace and scope in deterministic order."""

        keys = self._session.query(SqlIdempotencyKey.key).filter(
            SqlIdempotencyKey.workspace_id == self._workspace_id,
            SqlIdempotencyKey.scope == scope,
        )
        event_ids = [row[0] for row in keys]
        if not event_ids:
            return ()
        rows = (
            self._session.query(SqlHarnessEvent)
            .filter(
                SqlHarnessEvent.workspace_id == self._workspace_id,
                SqlHarnessEvent.run_id == run_id,
                SqlHarnessEvent.event_id.in_(
                    [_storage_event_id(scope, event_id) for event_id in event_ids]
                ),
            )
            .order_by(SqlHarnessEvent.sequence)
            .all()
        )
        return tuple(_decode_event(row) for row in rows)


def _storage_event_id(scope: str, event_id: str) -> str:
    """Derive a bounded physical identity while retaining the external ID."""

    return hashlib.sha256(f"{scope}\0{event_id}".encode()).hexdigest()
