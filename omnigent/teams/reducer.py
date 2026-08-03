"""Pure, explicit transitions for the team harness run ledger."""

from __future__ import annotations

from dataclasses import dataclass, replace

from omnigent.entities.run import RunStatus
from omnigent.teams.events import ActorType, EventType, LedgerEvent, LedgerStore
from omnigent.teams.states import RunState


class InvalidTransitionError(ValueError):
    """A ledger event does not permit a transition from the current state."""


@dataclass(frozen=True)
class Reduction:
    """The state and append-only audit records produced by one event."""

    state: RunState
    audit_events: tuple[LedgerEvent, ...] = ()
    coordinator_wake: bool = False


def _audit_event(event: LedgerEvent, event_type: EventType) -> LedgerEvent:
    return LedgerEvent(
        event_id=f"{event.event_id}:{event_type}",
        run_id=event.run_id,
        event_type=event_type,
        actor_type=ActorType.SYSTEM,
        actor_id="system",
        occurred_at=event.occurred_at,
        payload={"triggering_event_id": event.event_id},
        correlation_id=event.correlation_id,
    )


def _transition(state: RunState, event: LedgerEvent, status: RunStatus) -> Reduction:
    return Reduction(
        state=replace(
            state,
            status=status,
            applied_event_ids=state.applied_event_ids | {event.event_id},
        )
    )


def reduce_event(state: RunState, event: LedgerEvent) -> Reduction:
    """Reduce an event without mutating input state or performing I/O."""

    if event.run_id != state.run_id:
        raise ValueError(f"event run {event.run_id!r} does not match state run {state.run_id!r}")
    if event.event_id in state.applied_event_ids:
        return Reduction(state=state)

    if event.event_type is EventType.RUN_STARTED:
        if event.actor_type not in {ActorType.COORDINATOR, ActorType.SYSTEM, ActorType.USER}:
            raise InvalidTransitionError("worker cannot start a run")
        if state.status is not RunStatus.QUEUED:
            raise InvalidTransitionError(
                f"cannot transition {state.status.value} to {RunStatus.RUNNING.value}"
            )
        return _transition(state, event, RunStatus.RUNNING)

    if event.event_type is EventType.CANCEL_RUN:
        if event.actor_type not in {ActorType.COORDINATOR, ActorType.SYSTEM, ActorType.USER}:
            raise InvalidTransitionError("worker cannot cancel a run")
        if state.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise InvalidTransitionError(
                f"cannot transition {state.status.value} to {RunStatus.CANCELLED.value}"
            )
        result = _transition(state, event, RunStatus.CANCELLED)
        return replace(result, audit_events=(_audit_event(event, EventType.RUN_CANCELLED),))

    if event.event_type is EventType.WORKER_COMPLETED:
        if event.actor_type is not ActorType.WORKER:
            raise InvalidTransitionError("only a worker can complete work")
        if state.status is not RunStatus.RUNNING:
            raise InvalidTransitionError(
                f"cannot handle worker completion while run is {state.status.value}"
            )
        correlation_id = event.correlation_id or event.event_id
        next_state = replace(
            state,
            applied_event_ids=state.applied_event_ids | {event.event_id},
        )
        if correlation_id in state.coordinator_wake_correlation_ids:
            return Reduction(state=next_state)
        next_state = replace(
            next_state,
            coordinator_wake_correlation_ids=(
                state.coordinator_wake_correlation_ids | {correlation_id}
            ),
        )
        return Reduction(
            state=next_state,
            audit_events=(_audit_event(event, EventType.COORDINATOR_WOKEN),),
            coordinator_wake=True,
        )

    if event.event_type is EventType.RUN_CANCELLED:
        if event.actor_type is not ActorType.SYSTEM:
            raise InvalidTransitionError("only the system can record run cancellation")
        if state.status not in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLED}:
            raise InvalidTransitionError(
                f"cannot transition {state.status.value} to {RunStatus.CANCELLED.value}"
            )
        return _transition(state, event, RunStatus.CANCELLED)

    if event.event_type is EventType.COORDINATOR_WOKEN:
        if event.actor_type is not ActorType.SYSTEM:
            raise InvalidTransitionError("only the system can wake the coordinator")
        if state.status is not RunStatus.RUNNING:
            raise InvalidTransitionError(
                f"cannot wake coordinator while run is {state.status.value}"
            )
        correlation_id = event.correlation_id or event.event_id
        return Reduction(
            state=replace(
                state,
                applied_event_ids=state.applied_event_ids | {event.event_id},
                coordinator_wake_correlation_ids=(
                    state.coordinator_wake_correlation_ids | {correlation_id}
                ),
            )
        )

    raise InvalidTransitionError(f"unsupported event type: {event.event_type!r}")


def append_reduction(
    store: LedgerStore, scope: str, state: RunState, event: LedgerEvent
) -> Reduction:
    """Validate, append, and persist derived audit events from one reduction."""

    reduction = reduce_event(state, event)
    if event.event_id in state.applied_event_ids:
        return reduction
    if not store.append(scope, event):
        return Reduction(state=state)
    for audit_event in reduction.audit_events:
        store.append(scope, audit_event)
    return reduction


def replay_events(
    initial_state: RunState, events: tuple[LedgerEvent, ...] | list[LedgerEvent]
) -> RunState:
    """Rebuild state from an ordered durable event stream."""

    state = initial_state
    for event in events:
        state = reduce_event(state, event).state
    return state
