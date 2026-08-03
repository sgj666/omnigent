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
                 resolver: Callable[[str, str | None], RouteContext | None] | None = None,
                 coordinator_callback: Callable[[RunRequest], Any] | None = None,
                 action_callback: Callable[[RouteContext, LarkCardAction], Any] | None = None,
                 ) -> None:
        self.bindings = dict(bindings or {})
        self.resolver = resolver
        self.coordinator_callback = coordinator_callback
        self.action_callback = action_callback

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
        if self.coordinator_callback is not None:
            return self.coordinator_callback(request)
        coordinator = context.coordinator
        if hasattr(coordinator, "start_run"):
            return coordinator.start_run(request)
        if hasattr(coordinator, "submit"):
            return coordinator.submit(request)
        if hasattr(coordinator, "request_run"):
            return coordinator.request_run(request)
        # Explicit callback is preferred; no arbitrary method dispatch.
        raise LarkRoutingError("coordinator_unavailable", "Coordinator bridge is not configured")

    def authorize_action(self, event: LarkCardAction) -> RouteContext:
        context = self.resolve(event.chat_id, event.thread_id)
        if context.members and event.actor_id not in context.members:
            raise LarkRoutingError(
                "forbidden", "Lark member is not allowed to trigger this action"
            )
        return context

    def route_action(self, event: LarkCardAction) -> Any:
        context = self.authorize_action(event)
        allowed = {"retry", "cancel", "approve", "rerun"}
        if event.action_id not in allowed:
            raise LarkRoutingError("action_forbidden", "Card action is not in the allow-list")
        team_id = self._id(context.team)
        value_team = event.value.get("team_id")
        if value_team is not None and value_team != team_id:
            raise LarkRoutingError("binding_mismatch", "Card action Team binding mismatch")
        if context.workspace_id and event.value.get("workspace_id") not in (
            None,
            context.workspace_id,
        ):
            raise LarkRoutingError("binding_mismatch", "Card action workspace binding mismatch")
        validator = getattr(context.coordinator, "validate_action", None)
        if callable(validator) and not validator(event):
            raise LarkRoutingError(
                "invalid_transition", "Card action is not legal in current state"
            )
        if self.action_callback is not None:
            return self.action_callback(context, event)
        if hasattr(context.coordinator, "handle_action"):
            return context.coordinator.handle_action(event)
        raise LarkRoutingError("action_unavailable", "Coordinator action bridge is not configured")
