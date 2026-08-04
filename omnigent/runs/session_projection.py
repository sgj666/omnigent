"""Best-effort projection of authoritative Session execution facts."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from omnigent.entities.run_projection import ProjectionEvent, ProjectionResult, Run

_logger = logging.getLogger(__name__)


class _Store(Protocol):
    def apply_projection_event(self, event: ProjectionEvent) -> ProjectionResult: ...

    def get_run_by_root_session_id(self, root_session_id: str) -> Run | None: ...

    def get_latest_attempt_for_child(
        self, run_id: str, child_session_id: str
    ) -> tuple[Any, Any] | None: ...


class SessionRunProjection:
    """Observe Session facts without participating in execution decisions."""

    def __init__(self, store: _Store) -> None:
        self._store = store

    def root_created(self, run: Run) -> ProjectionResult | None:
        return self._apply(
            ProjectionEvent(
                source="session-runtime",
                source_event_id=f"root:{run.root_session_id}",
                event_type="run.root.created",
                run_id=run.id,
                session_id=run.root_session_id,
            )
        )

    def child_created(self, child: Any) -> ProjectionResult | None:
        run = self._run_for_conversation(child)
        if run is None:
            return None
        return self._apply(
            ProjectionEvent(
                source="session-runtime",
                source_event_id=f"child:{child.id}",
                event_type="session.child.created",
                run_id=run.id,
                session_id=child.id,
                payload={"parent_session_id": child.parent_conversation_id or ""},
            )
        )

    def dispatch_accepted(
        self,
        child: Any,
        *,
        conversation_item_id: str,
        logical_task_id: str | None = None,
    ) -> ProjectionResult | None:
        run = self._run_for_conversation(child)
        if run is None or getattr(child, "kind", None) != "sub_agent":
            return None
        worker_name, title = _worker_and_title(child)
        payload = {
            "child_session_id": child.id,
            "worker_name": worker_name,
            "title": title,
            "dispatch_call_id": conversation_item_id,
        }
        if logical_task_id is not None:
            payload["logical_task_id"] = logical_task_id
        harness = getattr(child, "harness_override", None)
        model = getattr(child, "model_override", None)
        if isinstance(harness, str) and harness:
            payload["harness"] = harness
        if isinstance(model, str) and model:
            payload["model"] = model
        return self._apply(
            ProjectionEvent(
                source="session-runtime",
                source_event_id=f"dispatch:{child.id}:{conversation_item_id}",
                event_type="dispatch.created",
                run_id=run.id,
                session_id=child.id,
                conversation_item_id=conversation_item_id,
                payload=payload,
            )
        )

    def terminal(
        self,
        child: Any,
        *,
        status: str,
        response_id: str | None = None,
        conversation_item_id: str | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> ProjectionResult | None:
        lifecycle = {
            "idle": "session.completed",
            "completed": "session.completed",
            "failed": "session.failed",
            "cancelled": "session.cancelled",
            "running": "session.running",
        }.get(status)
        if lifecycle is None:
            return None
        resolved = self._latest(child)
        if resolved is None:
            return None
        run, task, attempt = resolved
        payload = _failure_payload(failure_code, failure_message)
        if response_id is not None:
            payload["response_id"] = response_id
        return self._apply(
            ProjectionEvent(
                source="session-runtime",
                source_event_id=f"lifecycle:{attempt.id}:{lifecycle}",
                event_type=lifecycle,
                run_id=run.id,
                task_id=task.id,
                attempt_id=attempt.id,
                session_id=child.id,
                conversation_item_id=conversation_item_id,
                payload=payload,
            )
        )

    def blocked(
        self,
        child: Any,
        *,
        block_id: str,
        reason: str,
    ) -> ProjectionResult | None:
        resolved = self._latest(child)
        if resolved is None:
            return None
        run, task, attempt = resolved
        return self._apply(
            ProjectionEvent(
                source="session-runtime",
                source_event_id=f"blocked:{attempt.id}:{block_id}",
                event_type="session.blocked",
                run_id=run.id,
                task_id=task.id,
                attempt_id=attempt.id,
                session_id=child.id,
                payload={"failure_code": "blocked", "failure_message": reason},
            )
        )

    def parent_inbox_relayed(
        self,
        child: Any,
        *,
        status: str,
        conversation_item_id: str | None = None,
    ) -> ProjectionResult | None:
        resolved = self._latest(child)
        if resolved is None:
            return None
        run, task, attempt = resolved
        return self._apply(
            ProjectionEvent(
                source="session-runtime",
                source_event_id=f"parent-inbox:{attempt.id}:{status}",
                event_type="parent_inbox.relayed",
                run_id=run.id,
                task_id=task.id,
                attempt_id=attempt.id,
                session_id=child.id,
                conversation_item_id=conversation_item_id,
                payload={"status": status},
            )
        )

    def dependency(
        self,
        run: Run,
        *,
        task_id: str,
        depends_on_task_id: str,
        source_event_id: str,
    ) -> ProjectionResult | None:
        return self._apply(
            ProjectionEvent(
                source="session-runtime",
                source_event_id=f"dependency:{source_event_id}",
                event_type="plan.dependency",
                run_id=run.id,
                session_id=run.root_session_id,
                payload={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        )

    def _run_for_conversation(self, conversation: Any) -> Run | None:
        root_id = getattr(conversation, "root_conversation_id", None)
        if not isinstance(root_id, str) or not root_id:
            return None
        try:
            return self._store.get_run_by_root_session_id(root_id)
        except Exception:
            _logger.exception(
                "Run projection lookup failed for session=%s",
                getattr(conversation, "id", None),
            )
            return None

    def _latest(self, child: Any) -> tuple[Run, Any, Any] | None:
        run = self._run_for_conversation(child)
        if run is None:
            return None
        try:
            pair = self._store.get_latest_attempt_for_child(run.id, child.id)
        except Exception:
            _logger.exception("Run projection attempt lookup failed for session=%s", child.id)
            return None
        if pair is None:
            return None
        return run, pair[0], pair[1]

    def _apply(self, event: ProjectionEvent) -> ProjectionResult | None:
        try:
            return self._store.apply_projection_event(event)
        except Exception:
            _logger.exception(
                "Run projection failed for event=%s source_event_id=%s",
                event.event_type,
                event.source_event_id,
            )
            return None


def observe(projection: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Invoke one optional projection hook without affecting Session execution."""
    if projection is None:
        return None
    try:
        callback = getattr(projection, method)
        return callback(*args, **kwargs)
    except Exception:
        _logger.exception("Run projection observer hook failed: %s", method)
        return None


def _worker_and_title(child: Any) -> tuple[str, str]:
    raw_title = str(getattr(child, "title", "") or child.id)
    worker = str(getattr(child, "sub_agent_name", "") or raw_title.partition(":")[0])
    return worker, canonical_dispatch_title(worker, raw_title)


def canonical_dispatch_title(worker: str, raw_title: str) -> str:
    """Return the Task title shared by reservation and Session projection."""
    prefix = f"{worker}:"
    return raw_title[len(prefix) :] if raw_title.startswith(prefix) else raw_title


def _failure_payload(code: str | None, message: str | None) -> dict[str, str]:
    payload: dict[str, str] = {}
    if code:
        payload["failure_code"] = code
    if message:
        payload["failure_message"] = message
    return payload
