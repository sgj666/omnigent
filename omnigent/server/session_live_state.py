"""Best-effort persistence of per-session live state to the conversations table.

The sidebar's live fields — ``runner_online``, turn ``status``, and the
pending-approval count — were historically served from in-memory caches
that exist only on the server replica holding a session's runner tunnel
(the tunnel registry, the SSE-relay status cache, and the
pending-elicitations index). Under host_id replica sharding a session
list / ``WS /v1/sessions/updates`` request can land on any replica, so
those fields must also live somewhere every replica can read: the
``conversations`` row (regional DB).

This module is the single write chokepoint. The in-memory caches remain
the synchronous source on the tunnel-holding replica; every cache write
also enqueues a row write here. Writes are:

- **best-effort** — a failed write logs and is dropped; live state is
  display state, and the next transition rewrites it. A dropped write
  also evicts its dedupe entry, so the next *identical* publish is not
  swallowed and gets a fresh attempt (see :func:`_submit`).
- **ordered** — a single-worker executor serializes writes, so a
  ``running`` → ``idle`` pair can never apply out of order.
- **off the event loop** — the store is synchronous SQLAlchemy; callers
  (the SSE relay, the tunnel handlers, the pub-sub hot path) only pay a
  dict check and a queue put. The write runs in a copy of the caller's
  ``contextvars`` (see :func:`_submit`) so the per-request
  ``workspace_scope`` — which every store query filters on — reaches the
  worker thread; a bare executor would run at the default workspace and
  every ``WHERE workspace_id == …`` would match no rows on a multi-tenant
  replica.
- **deduplicated** — re-publishing an unchanged status / count is a
  no-op, so chatty relays don't turn into row churn.

No-op until :func:`configure` wires a store (the server app does this at
startup); the runner process and unit tests that never configure it are
unaffected.
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from omnigent.db.enum_codecs import SESSION_LIVE_STATUS

if TYPE_CHECKING:
    from omnigent.entities import WorkItemRun
    from omnigent.stores import ConversationStore
    from omnigent.stores.file_store import FileStore
    from omnigent.stores.inbox_item_store import InboxItemStore
    from omnigent.stores.scheduled_task_store import ScheduledTaskStore
    from omnigent.stores.work_item_run_store import WorkItemRunStore
    from omnigent.stores.work_item_store import WorkItemStore

from omnigent.runtime import user_session_stream

_logger = logging.getLogger(__name__)

# Statuses the live-status codec can encode. Derived from the codec's own
# map so the two never drift. ``SessionStatusEvent.status`` additionally
# permits ``"launching"`` (runner-local sub-agent bookkeeping that never
# rides as an external ``session.status`` today), which the codec can't
# encode — see ``persist_live_status``.
_KNOWN_LIVE_STATUSES: frozenset[str] = frozenset(SESSION_LIVE_STATUS)

_store: ConversationStore | None = None
# Scheduled-task store for the event-driven run-completion hook. Wired
# alongside ``_store`` by :func:`configure`; ``None`` disables the hook (the
# runner process and unit tests that never configure it are unaffected).
_scheduled_task_store: ScheduledTaskStore | None = None
_work_item_run_store: WorkItemRunStore | None = None
_work_item_store: WorkItemStore | None = None
_inbox_item_store: InboxItemStore | None = None
_file_store: FileStore | None = None
# Single worker => writes apply in submission order (see module docstring).
_executor: ThreadPoolExecutor | None = None
# Last status seen per session, for dedupe — the value whose write was
# enqueued, or (for an unencodable status) the value whose warning was
# already logged, so repeats of either are suppressed. Unbounded like the
# in-memory caches these writes mirror; entries live for the process.
_last_status: dict[str, str] = {}
# Last count persisted per session, for dedupe.
_last_pending: dict[str, int] = {}


def configure(
    store: ConversationStore | None,
    scheduled_task_store: ScheduledTaskStore | None = None,
    work_item_run_store: WorkItemRunStore | None = None,
    work_item_store: WorkItemStore | None = None,
    inbox_item_store: InboxItemStore | None = None,
    file_store: FileStore | None = None,
) -> None:
    """
    Wire (or clear) the stores live-state writes go to.

    :param store: The server's conversation store, or ``None`` to
        disable persistence (tests / non-server processes).
    :param scheduled_task_store: The server's scheduled-task store, enabling
        the event-driven run-completion hook
        (:func:`persist_scheduled_run_completion`); ``None`` disables it.
    """
    global \
        _store, \
        _scheduled_task_store, \
        _work_item_run_store, \
        _work_item_store, \
        _inbox_item_store, \
        _file_store
    _store = store
    _scheduled_task_store = scheduled_task_store
    _work_item_run_store = work_item_run_store
    _work_item_store = work_item_store
    _inbox_item_store = inbox_item_store
    _file_store = file_store
    _last_status.clear()
    _last_pending.clear()


def _submit(description: str, fn, *args, on_failure=None, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """
    Run one store write on the ordered background worker.

    The write runs inside a snapshot of the *caller's* ``contextvars``
    (``copy_context().run``). The store filters every query on
    ``current_workspace_id()``, a ``ContextVar`` the multi-tenant request
    middleware binds per request via ``workspace_scope``; a bare
    ``ThreadPoolExecutor.submit`` would run the write at the default
    workspace (0), so on a multi-tenant replica every
    ``UPDATE ... WHERE workspace_id == …`` would match no rows and the
    whole cross-replica mirror would silently no-op. Copying the context
    is the same thing ``asyncio.to_thread`` (used on the read path) does.

    :param description: Log label on failure, e.g. ``"live_status"``.
    :param fn: The store method to call.
    :param args: Arguments for *fn*.
    :param on_failure: Optional zero-arg callback run (on the worker
        thread) when the write raises. Used to evict a dedupe entry so a
        dropped write's value can be re-attempted by the next identical
        publish instead of being swallowed.
    """
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-live-state")

    ctx = contextvars.copy_context()

    def _run() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 — best-effort display state
            _logger.warning("session live-state write failed (%s)", description, exc_info=True)
            if on_failure is not None:
                on_failure()

    _executor.submit(ctx.run, _run)


def persist_live_status(session_id: str, status: str) -> None:
    """
    Persist a relay-observed turn status transition.

    Called wherever ``_session_status_cache`` is written. Deduplicated:
    only an actual transition reaches the database.

    :param session_id: Session/conversation identifier.
    :param status: One of ``idle`` / ``running`` / ``waiting`` / ``failed``.
    """
    if _store is None:
        return
    if status not in _KNOWN_LIVE_STATUSES:
        # ``SessionStatusEvent.status`` permits values the live-status codec
        # can't encode (``"launching"``), and the relay forwards raw event
        # statuses. Drop unknown values here rather than at the store: the
        # encode would raise, and the best-effort ``_evict`` on that failure
        # would clear the dedupe entry, so every republish would re-attempt
        # and re-log. Warn once (this transition is deduped away) and skip.
        if _last_status.get(session_id) != status:
            _logger.warning(
                "session live-state: skipping unencodable status %r for %s",
                status,
                session_id,
            )
        _last_status[session_id] = status
        return
    if _last_status.get(session_id) == status:
        return
    _last_status[session_id] = status

    def _evict() -> None:
        # A dropped write must not leave the dedupe cache asserting this
        # value reached the DB — otherwise a later identical publish is
        # swallowed and the row stays stale until a *different* status
        # arrives. Evict only if we still own the entry (a newer publish
        # may have overwritten it, and its write is the live one).
        if _last_status.get(session_id) == status:
            _last_status.pop(session_id, None)

    _submit("live_status", _store.set_session_live_status, session_id, status, on_failure=_evict)


def persist_scheduled_run_completion(
    conversation_id: str,
    run_status: str,
    *,
    error_code: str | None = None,
    error: str | None = None,
) -> None:
    """Transition a scheduled-task run to terminal when its turn ends.

    The event-driven completion mechanism: called from ``_publish_status``
    wherever a session reaches a durable terminal edge (``idle`` = the turn
    completed, ``failed`` = it errored/disconnected). Most conversations are
    not scheduled-task fires, so the reverse lookup returns ``None`` and this
    is a cheap no-op; only a fired conversation with a still-``running`` run
    gets transitioned.

    Runs on the SAME ordered single-worker executor as
    :func:`persist_live_status`, inside a copy of the caller's ``contextvars``
    (see :func:`_submit`). This is load-bearing: the store filters every query
    on ``current_workspace_id()``, and the reverse lookup + ``update_run`` must
    resolve to the fired run's workspace — the relay call site's
    ``workspace_scope`` reaches the worker thread exactly as it does for the
    ``live_status`` mirror. A bare executor would run at workspace 0 and match
    no rows on a multi-tenant replica.

    Idempotent by construction: ``update_run`` is conditional on
    ``WHERE status = running``, so a run already terminal (a fire-time
    ``skipped``/``failed``, or the startup/lazy backstop) is never clobbered
    and a terminal edge seen twice transitions at most once. Best-effort like
    the other writes here — a failure logs and is dropped; the backstop
    (startup sweep / lazy-on-read) is the durability guarantee for the rare
    dropped-write or restart-in-flight case.

    :param conversation_id: The fired conversation whose turn just ended.
    :param run_status: Terminal run status to set — ``"succeeded"`` (turn
        completed) or ``"failed"`` (turn errored/cancelled/disconnected).
    :param error_code: Short failure classification when ``run_status`` is
        ``"failed"`` (e.g. the conversation's ``last_task_error_code``).
    :param error: Optional human-readable failure detail for ``"failed"``.
    """
    store = _scheduled_task_store
    if store is None:
        return

    def _transition() -> None:
        run = store.get_running_run_by_conversation(conversation_id)
        if run is None:
            # Not a scheduled fire, or its run is already terminal — nothing to
            # do. This is the common case (interactive sessions).
            return
        store.update_run(
            run.id,
            status=run_status,
            finished_at=int(time.time()),
            error=error,
            error_code=error_code,
        )

    _submit("scheduled_run_completion", _transition)


def persist_work_item_run_status(
    session_id: str,
    session_status: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    response_id: str | None = None,
) -> None:
    """Project an authoritative Session status onto its product TaskRun."""
    run_store = _work_item_run_store
    inbox_store = _inbox_item_store
    if run_store is None and inbox_store is None:
        return
    state = {
        "running": "running",
        "waiting": "waiting",
        "idle": "succeeded",
        "failed": "failed",
    }.get(session_status)
    if state is None:
        return

    def _transition_and_notify() -> None:
        run = (
            run_store.transition_for_session(
                session_id,
                state=state,
                failure_code=error_code,
                failure_message=error_message,
                failure_retryable=error_code
                in {"internal_error", "runner_unavailable", "runner_capability_mismatch"},
            )
            if run_store is not None
            else None
        )
        if run is not None and state in {"succeeded", "failed", "cancelled"}:
            run = _record_work_item_run_result(run)
        if run is not None:
            _project_work_item_state(run, state)
        if inbox_store is None:
            return
        if run is not None:
            kind = {
                "waiting": "task_waiting",
                "succeeded": "task_succeeded",
                "failed": "task_failed",
            }.get(state)
            if kind is None:
                return
            task = (
                _work_item_store.get(run.work_item_id, owner_user_id=run.owner_user_id)
                if _work_item_store is not None
                else None
            )
            _create_inbox_item(
                owner_user_id=run.owner_user_id,
                kind=kind,
                event_key=f"work-item-run:{run.id}:{state}",
                work_item_id=run.work_item_id,
                work_item_run_id=run.id,
                session_id=session_id,
                message=task.title if task is not None else None,
                target_url=f"/tasks/{run.work_item_id}",
                action_required=state in {"waiting", "failed"},
            )
            return
        if response_id is None or state not in {"succeeded", "failed"} or _store is None:
            return
        conversation = _store.get_conversation(session_id)
        if conversation is None:
            return
        owner = _store.get_session_owner(session_id)
        _create_inbox_item(
            owner_user_id=owner,
            kind="session_completed" if state == "succeeded" else "session_failed",
            event_key=f"session:{session_id}:{state}:{response_id}",
            session_id=session_id,
            source_id=response_id,
            message=conversation.title or None,
            target_url=f"/c/{session_id}",
            action_required=state == "failed",
        )

    _submit("work_item_run_status", _transition_and_notify)


def _project_work_item_state(run: object, run_state: str) -> None:
    """Reflect authoritative execution outcomes on a non-terminal Task."""
    if _work_item_store is None:
        return
    target = {
        "running": "in_progress",
        "waiting": "blocked",
        "succeeded": "review",
        "failed": "failed",
    }.get(run_state)
    if target is None:
        return
    task = _work_item_store.get(run.work_item_id, owner_user_id=run.owner_user_id)
    if task is None or task.state.value in {"done", "cancelled"} or task.state.value == target:
        return
    try:
        updated = _work_item_store.update(
            task.id,
            owner_user_id=task.owner_user_id,
            expected_version=task.version,
            changes={"state": target},
        )
        if updated is not None:
            user_session_stream.publish(
                user_session_stream.user_key(task.owner_user_id),
                {"type": "work_items_changed"},
            )
    except Exception:  # noqa: BLE001 - a concurrent manual move wins
        _logger.debug("Could not project TaskRun state onto Task %s", task.id, exc_info=True)


def persist_work_item_run_cancelled(session_id: str) -> None:
    """Project an explicit Session stop as TaskRun cancellation."""
    store = _work_item_run_store
    if store is None:
        return

    def _cancel_and_notify() -> None:
        run = store.transition_for_session(session_id, state="cancelled")
        if run is None:
            return
        run = _record_work_item_run_result(run)
        task = (
            _work_item_store.get(run.work_item_id, owner_user_id=run.owner_user_id)
            if _work_item_store is not None
            else None
        )
        _create_inbox_item(
            owner_user_id=run.owner_user_id,
            kind="task_cancelled",
            event_key=f"work-item-run:{run.id}:cancelled",
            work_item_id=run.work_item_id,
            work_item_run_id=run.id,
            session_id=session_id,
            message=task.title if task is not None else None,
            target_url=f"/tasks/{run.work_item_id}",
        )

    _submit("work_item_run_cancelled", _cancel_and_notify)


def _record_work_item_run_result(run: WorkItemRun) -> WorkItemRun:
    """Best-effort projection of Session output onto a terminal TaskRun."""
    if _store is None or _file_store is None or _work_item_run_store is None:
        return run
    if run.session_id is None:
        return run
    try:
        from omnigent.project_artifacts import collect_session_run_result

        result = collect_session_run_result(_store, _file_store, run.session_id)
        updated = _work_item_run_store.record_result_for_session(
            run.session_id,
            result_summary=result.summary,
            artifact_refs=result.artifact_refs,
        )
        return updated or run
    except Exception:  # noqa: BLE001 - lifecycle projection remains best-effort
        _logger.warning(
            "TaskRun result projection failed for session %s",
            run.session_id,
            exc_info=True,
        )
        return run


def _owner_dedupe_key(owner_user_id: str | None, event_key: str) -> str:
    return f"{owner_user_id or 'local'}:{event_key}"


def _create_inbox_item(
    *,
    owner_user_id: str | None,
    kind: str,
    event_key: str,
    target_url: str,
    work_item_id: str | None = None,
    work_item_run_id: str | None = None,
    session_id: str | None = None,
    source_id: str | None = None,
    message: str | None = None,
    action_required: bool = False,
) -> None:
    store = _inbox_item_store
    if store is None:
        return
    _item, created = store.create_if_absent(
        uuid.uuid4().hex,
        owner_user_id=owner_user_id,
        kind=kind,
        dedupe_key=_owner_dedupe_key(owner_user_id, event_key),
        work_item_id=work_item_id,
        work_item_run_id=work_item_run_id,
        session_id=session_id,
        source_id=source_id,
        message=message,
        target_url=target_url,
        action_required=action_required,
    )
    if created:
        user_session_stream.publish(
            user_session_stream.user_key(owner_user_id),
            {"type": "inbox_changed"},
        )


def persist_inbox_elicitation(session_id: str, event: dict[str, object]) -> None:
    """Persist or resolve a confirmation request by elicitation id."""
    if _inbox_item_store is None or _store is None:
        return
    elicitation_id = event.get("elicitation_id")
    if not isinstance(elicitation_id, str) or not elicitation_id:
        return
    event_type = event.get("type")

    def _persist() -> None:
        owner = _store.get_session_owner(session_id)
        event_key = f"elicitation:{elicitation_id}"
        if event_type == "response.elicitation_resolved":
            item = _inbox_item_store.resolve(_owner_dedupe_key(owner, event_key))
            if item is not None:
                user_session_stream.publish(
                    user_session_stream.user_key(owner), {"type": "inbox_changed"}
                )
            return
        params = event.get("params")
        message = params.get("message") if isinstance(params, dict) else None
        conversation = _store.get_conversation(session_id)
        _create_inbox_item(
            owner_user_id=owner,
            kind="approval_required",
            event_key=event_key,
            session_id=session_id,
            source_id=elicitation_id,
            message=(
                message
                if isinstance(message, str)
                else conversation.title
                if conversation
                else None
            ),
            target_url=f"/c/{session_id}",
            action_required=True,
        )

    _submit("inbox_elicitation", _persist)


def persist_work_item_completed(item: object) -> None:
    """Persist a notification for a Task entering ``done``."""
    if _inbox_item_store is None:
        return

    def _persist() -> None:
        completion_id = getattr(item, "completion_id", None)
        occurrence = completion_id or f"legacy-v{item.version}"
        _create_inbox_item(
            owner_user_id=item.owner_user_id,
            kind="task_completed",
            event_key=f"work-item:{item.id}:completed:{occurrence}",
            work_item_id=item.id,
            message=item.title,
            target_url=f"/tasks/{item.id}",
        )

    _submit("work_item_completed", _persist)


def persist_work_item_run_terminal(run: object) -> None:
    """Persist a launch-time failed TaskRun notification."""
    if _inbox_item_store is None or run.state.value not in {"failed", "cancelled"}:
        return

    def _persist() -> None:
        _project_work_item_state(run, run.state.value)
        task = (
            _work_item_store.get(run.work_item_id, owner_user_id=run.owner_user_id)
            if _work_item_store is not None
            else None
        )
        _create_inbox_item(
            owner_user_id=run.owner_user_id,
            kind=f"task_{run.state.value}",
            event_key=f"work-item-run:{run.id}:{run.state.value}",
            work_item_id=run.work_item_id,
            work_item_run_id=run.id,
            session_id=run.session_id,
            message=task.title if task is not None else None,
            target_url=f"/tasks/{run.work_item_id}",
            action_required=run.state.value == "failed",
        )

    _submit("work_item_run_terminal", _persist)


def persist_pending_count(conversation_id: str, count: int) -> None:
    """
    Persist an outstanding-elicitation count change.

    Wired as :func:`omnigent.runtime.pending_elicitations`'s persist
    hook; runs on the pub-sub hot path, so it must stay cheap.

    :param conversation_id: Session/conversation identifier.
    :param count: Outstanding elicitations, ``>= 0``.
    """
    if _store is None or _last_pending.get(conversation_id) == count:
        return
    _last_pending[conversation_id] = count

    def _evict() -> None:
        # See persist_live_status._evict: keep the dedupe cache honest so a
        # dropped count write can be re-attempted by the next publish.
        if _last_pending.get(conversation_id) == count:
            _last_pending.pop(conversation_id, None)

    _submit(
        "pending_count",
        _store.set_pending_elicitation_count,
        conversation_id,
        count,
        on_failure=_evict,
    )


def touch_runner_liveness(runner_ids: list[str]) -> None:
    """
    Stamp ``runner_last_seen`` (now) for sessions bound to live runners.

    Called on the tunnel-holding replica: once on runner-tunnel connect,
    then every ping interval from that tunnel's own ping loop
    (``runner_tunnel._ping_loop``). Re-stamping from the per-connection
    ping loop — rather than a central lifespan sweep over the whole
    registry — keeps the write inside the tunnel handler's
    ``workspace_scope``, so the row's ``workspace_id`` filter resolves to
    the owning workspace on a multi-tenant replica. It mirrors how the
    host tunnel refreshes ``host_store.heartbeat`` from its ping loop.

    :param runner_ids: Runner ids with a live tunnel. Empty = no-op.
    """
    if _store is None or not runner_ids:
        return
    _submit("runner_liveness", _store.touch_runner_liveness, list(runner_ids), int(time.time()))


def clear_runner_liveness(runner_id: str) -> None:
    """
    Clear ``runner_last_seen`` for a gracefully-disconnected runner.

    Flips the sidebar offline immediately instead of waiting out the
    freshness TTL. An ungraceful death (host / replica crash) never
    reaches this — the TTL self-corrects it.

    :param runner_id: The disconnected runner's id.
    """
    if _store is None:
        return
    _submit("runner_liveness_clear", _store.clear_runner_liveness, runner_id)
