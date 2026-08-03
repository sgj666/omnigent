"""Chat/thread to Team and Coordinator routing."""

# Team and Coordinator are injected duck-typed integrations.
# mypy: disable-error-code=explicit-any

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .protocol import LarkCardAction, LarkMessage


class LarkRoutingError(RuntimeError):
    """An inbound event cannot be safely routed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RunRequest:
    text: str
    actor: str
    actor_id: str
    team_id: str
    coordinator_id: str
    workspace_id: str | None
    chat_id: str
    thread_id: str | None
    mentions: tuple[str, ...] = ()


@dataclass
class RouteContext:
    team: Any
    coordinator: Any
    workspace_id: str | None = None
    members: set[str] = field(default_factory=set)


class LarkRouter:
    """Resolve a Lark conversation and submit all work to its Coordinator.

    ``bindings`` may be populated with :meth:`bind`; ``resolver`` is an
    optional callable for SQL-backed deployments and receives ``(chat, thread)``.
    """

    def __init__(self, *, bindings: Mapping[tuple[str, str | None], RouteContext] | None = None,
                 resolver: Callable[[str, str | None], RouteContext | None] | None = None) -> None:
        self.bindings = dict(bindings or {})
        self.resolver = resolver

    def bind(self, chat_id: str, team: Any, coordinator: Any, *, thread_id: str | None = None,
             workspace_id: str | None = None, members: set[str] | None = None) -> RouteContext:
        context = RouteContext(team, coordinator, workspace_id, set(members or ()))
        self.bindings[(chat_id, thread_id)] = context
        return context

    def resolve(self, chat_id: str, thread_id: str | None) -> RouteContext:
        context = self.bindings.get((chat_id, thread_id))
        if context is None and thread_id is None:
            context = self.bindings.get((chat_id, None))
        if context is None and self.resolver is not None:
            context = self.resolver(chat_id, thread_id)
        if context is None:
            raise LarkRoutingError(
                "unknown_thread",
                f"No Team binding for chat {chat_id!r} thread {thread_id!r}",
            )
        return context

    @staticmethod
    def _id(value: Any, fallback: str = "") -> str:
        return str(
            value.get("id", fallback)
            if isinstance(value, Mapping)
            else getattr(value, "id", fallback)
        )

    def route_message(self, event: LarkMessage) -> Any:
        context = self.resolve(event.chat_id, event.thread_id)
        if context.members and event.sender_id not in context.members:
            raise LarkRoutingError("forbidden", "Lark member is not allowed to send messages")
        team_id = self._id(context.team)
        coordinator_id = self._id(context.coordinator)
        request = RunRequest(event.text, "coordinator", event.sender_id, team_id, coordinator_id,
                             context.workspace_id, event.chat_id, event.thread_id, event.mentions)
        coordinator = context.coordinator
        for method in ("receive", "submit", "request_run", "handle_request"):
            callback = getattr(coordinator, method, None)
            if callback is not None:
                try:
                    return callback(request)
                except TypeError:
                    return callback(event.text)
        raise LarkRoutingError("coordinator_unavailable", "Team has no Coordinator entrypoint")

    def authorize_action(self, event: LarkCardAction) -> RouteContext:
        context = self.resolve(event.chat_id, event.thread_id)
        if context.members and event.actor_id not in context.members:
            raise LarkRoutingError(
                "forbidden", "Lark member is not allowed to trigger this action"
            )
        return context

    def route_action(self, event: LarkCardAction) -> Any:
        context = self.authorize_action(event)
        coordinator = context.coordinator
        for method in ("handle_action", "dispatch_action", "action"):
            callback = getattr(coordinator, method, None)
            if callback is not None:
                try:
                    return callback(event)
                except TypeError:
                    return callback(event.action_id, event.value)
        # Keep deterministic actions useful with tiny coordinator fakes.
        callback = getattr(coordinator, event.action_id, None)
        if callable(callback):
            return callback(event.value)
        raise LarkRoutingError(
            "action_unavailable", f"Coordinator cannot handle {event.action_id!r}"
        )
