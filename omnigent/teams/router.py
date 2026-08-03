"""Parent Inbox routing into the fixed Coordinator."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from omnigent.teams.coordinator import Coordinator


@dataclass(frozen=True)
class WorkerCompletedMessage:
    run_id: str
    task_id: str
    attempt_id: str
    event_id: str


class ParentInbox:
    """At-least-once inbox with event-id deduplication and automatic draining."""

    def __init__(self, coordinator: Coordinator | None = None) -> None:
        self.coordinator = coordinator
        self._seen: set[str] = set()
        self._queue: deque[WorkerCompletedMessage] = deque()

    def put(
        self,
        message: WorkerCompletedMessage | Mapping[str, object] | None = None,
        *,
        run_id: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        event_id: str | None = None,
    ) -> bool:
        """Queue one completion, returning false for a duplicate event."""

        if message is None:
            if run_id is None or task_id is None or attempt_id is None:
                raise ValueError("run_id, task_id and attempt_id are required")
            message = WorkerCompletedMessage(
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                event_id=event_id or f"worker-completed:{attempt_id}",
            )
        elif isinstance(message, Mapping):
            message = WorkerCompletedMessage(
                run_id=str(message["run_id"]),
                task_id=str(message["task_id"]),
                attempt_id=str(message["attempt_id"]),
                event_id=str(message.get("event_id", f"worker-completed:{message['attempt_id']}")),
            )
        if message.event_id in self._seen:
            return False
        self._seen.add(message.event_id)
        self._queue.append(message)
        if self.coordinator is not None:
            self.drain()
        return True

    publish = put
    publish_worker_completed = put

    def drain(self) -> int:
        """Wake the coordinator for all queued messages and return wake count."""

        if self.coordinator is None:
            return 0
        count = 0
        while self._queue:
            message = self._queue.popleft()
            self.coordinator.on_worker_completed(
                message.run_id, message.task_id, message.attempt_id
            )
            count += 1
        return count

    def __len__(self) -> int:
        return len(self._queue)


class CoordinatorRouter:
    """Translate structured worker messages to Parent Inbox calls."""

    def __init__(self, coordinator: Coordinator, inbox: ParentInbox | None = None) -> None:
        self.coordinator = coordinator
        self.inbox = inbox or ParentInbox(coordinator)

    def route_worker_completed(
        self,
        run_id: str,
        task_id: str,
        attempt_id: str,
        *,
        event_id: str | None = None,
    ) -> bool:
        return self.inbox.put(
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            event_id=event_id,
        )

    def route(self, message: Mapping[str, object]) -> bool:
        """Route a worker completion mapping; unknown messages are rejected."""

        if message.get("event_type", "worker_completed") not in {
            "worker_completed",
            "WORKER_COMPLETED",
        }:
            raise ValueError(f"unsupported parent inbox event: {message.get('event_type')!r}")
        return self.inbox.put(message)


Router = CoordinatorRouter

__all__ = ["CoordinatorRouter", "ParentInbox", "Router", "WorkerCompletedMessage"]
