"""Tests for the append-only team harness event reducer."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from omnigent.db.db_models import OmnigentBase, SqlHarnessEvent, SqlIdempotencyKey
from omnigent.teams.events import ActorType, EventType, LedgerEvent
from omnigent.teams.idempotency import SqlAlchemyLedgerStore
from omnigent.teams.reducer import (
    InvalidTransitionError,
    append_reduction,
    reduce_event,
    replay_events,
)
from omnigent.teams.states import RunState


def test_duplicate_worker_completed_wakes_coordinator_once() -> None:
    state = RunState.running("run-1")
    event = LedgerEvent(
        event_id="worker-completed-1",
        run_id="run-1",
        event_type=EventType.WORKER_COMPLETED,
        actor_type=ActorType.WORKER,
        actor_id="worker-1",
        occurred_at=1,
        payload={"attempt_id": "attempt-1"},
        correlation_id="attempt-1",
    )

    first = reduce_event(state, event)
    duplicate = reduce_event(first.state, event)

    assert first.coordinator_wake is True
    assert duplicate.coordinator_wake is False
    assert duplicate.state == first.state
    assert [audit.event_type for audit in first.audit_events] == [EventType.COORDINATOR_WOKEN]
    assert duplicate.audit_events == ()


def test_cancel_run_from_completed_state_is_rejected() -> None:
    state = RunState.completed("run-1")
    event = LedgerEvent(
        event_id="cancel-1",
        run_id="run-1",
        event_type=EventType.CANCEL_RUN,
        actor_type=ActorType.USER,
        actor_id="user-1",
        occurred_at=1,
        payload={},
        correlation_id=None,
    )

    with pytest.raises(InvalidTransitionError, match=r"completed.*cancelled"):
        reduce_event(state, event)


def test_sql_store_round_trip_survives_new_session_and_is_scope_isolated() -> None:
    run_id = "0123456789abcdef0123456789abcdef"
    engine = sa.create_engine("sqlite://")
    OmnigentBase.metadata.create_all(
        engine, tables=[SqlHarnessEvent.__table__, SqlIdempotencyKey.__table__]
    )
    event = LedgerEvent(
        event_id="worker-completed-2",
        run_id=run_id,
        event_type=EventType.WORKER_COMPLETED,
        actor_type=ActorType.WORKER,
        actor_id="worker-2",
        occurred_at=2,
        payload={"nested": {"result": [1, "ok"]}},
        correlation_id="corr-2",
    )

    with Session(engine) as session:
        store = SqlAlchemyLedgerStore(session, workspace_id=1)
        assert store.append("feishu", event) is True
        assert store.append("feishu", event) is False
        session.commit()

    with Session(engine) as session:
        restarted = SqlAlchemyLedgerStore(session, workspace_id=1)
        loaded = restarted.list_events("feishu", run_id)
        assert loaded == (event,)
        assert restarted.append("api", event) is True
        assert restarted.list_events("api", run_id) == (event,)
        isolated = SqlAlchemyLedgerStore(session, workspace_id=2)
        assert isolated.append("feishu", event) is True


def test_equal_timestamp_events_replay_in_append_sequence() -> None:
    run_id = "0123456789abcdef0123456789abcdef"
    engine = sa.create_engine("sqlite://")
    OmnigentBase.metadata.create_all(
        engine, tables=[SqlHarnessEvent.__table__, SqlIdempotencyKey.__table__]
    )
    events = tuple(
        LedgerEvent(
            event_id=f"worker-completed-{event_id}",
            run_id=run_id,
            event_type=EventType.WORKER_COMPLETED,
            actor_type=ActorType.WORKER,
            actor_id=f"worker-{event_id}",
            occurred_at=10,
            payload={},
            correlation_id=f"corr-{event_id}",
        )
        for event_id in ("first", "second")
    )

    with Session(engine) as session:
        store = SqlAlchemyLedgerStore(session, workspace_id=1)
        assert all(store.append("feishu", event) for event in events)
        session.commit()

    with Session(engine) as session:
        restarted = SqlAlchemyLedgerStore(session, workspace_id=1)
        assert restarted.list_events("feishu", run_id) == events


def test_append_reduction_persists_audit_and_replay_reconstructs_wake() -> None:
    run_id = "0123456789abcdef0123456789abcdef"
    engine = sa.create_engine("sqlite://")
    OmnigentBase.metadata.create_all(
        engine, tables=[SqlHarnessEvent.__table__, SqlIdempotencyKey.__table__]
    )
    event = LedgerEvent(
        event_id="worker-completed-3",
        run_id=run_id,
        event_type=EventType.WORKER_COMPLETED,
        actor_type=ActorType.WORKER,
        actor_id="worker-3",
        occurred_at=3,
        payload={},
        correlation_id="corr-3",
    )

    with Session(engine) as session:
        store = SqlAlchemyLedgerStore(session, workspace_id=1)
        result = append_reduction(store, "feishu", RunState.running(run_id), event)
        duplicate = append_reduction(store, "feishu", RunState.running(run_id), event)
        session.commit()
        assert result.coordinator_wake is True
        assert duplicate.coordinator_wake is False

    with Session(engine) as session:
        events = SqlAlchemyLedgerStore(session, workspace_id=1).list_events("feishu", run_id)
        assert [item.event_type for item in events] == [
            EventType.WORKER_COMPLETED,
            EventType.COORDINATOR_WOKEN,
        ]
        rebuilt = replay_events(RunState.running(run_id), tuple(events))
        assert rebuilt.coordinator_wake_correlation_ids == frozenset({"corr-3"})
