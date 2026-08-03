"""Append-only events emitted by a team harness run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ActorType(StrEnum):
    """The principal that emitted a ledger event."""

    COORDINATOR = "coordinator"
    WORKER = "worker"
    SYSTEM = "system"
    USER = "user"


class EventType(StrEnum):
    """Events understood by the run reducer."""

    RUN_STARTED = "run_started"
    WORKER_COMPLETED = "worker_completed"
    CANCEL_RUN = "cancel_run"
    RUN_CANCELLED = "run_cancelled"
    COORDINATOR_WOKEN = "coordinator_woken"


@dataclass(frozen=True)
class LedgerEvent:
    """An immutable, externally identified record in a run ledger."""

    event_id: str
    run_id: str
    event_type: EventType
    actor_type: ActorType
    actor_id: str
    occurred_at: int
    payload: Mapping[str, object]
    correlation_id: str | None


class LedgerStore(Protocol):
    """Durable append/replay boundary for ledger events."""

    def append(self, scope: str, event: LedgerEvent) -> bool:
        """Append *event* once for *scope*, returning false for duplicates."""

    def list_events(self, scope: str, run_id: str) -> Sequence[LedgerEvent]:
        """Return events for a run in occurred-at/order insertion order."""
