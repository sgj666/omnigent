"""Deterministic Feishu seams used by the team-harness acceptance tests.

The fake intentionally models provider boundaries (QR polling, WebSocket
connectivity, cards and notifications) without making network calls.  It is
also useful to downstream integration tests that need to inject a transient
provider failure and then replay the same event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FakeNotification:
    kind: str
    run_id: str
    payload: dict[str, Any] = field(default_factory=dict)


class FakeLark:
    """Small in-memory PersonalAgent/WebSocket/Card provider."""

    def __init__(self) -> None:
        self.begin_result: dict[str, Any] = {
            "session": "install-1",
            "verification_uri_complete": "https://lark.test/scan/install-1",
            "interval": 1,
            "expires_in": 60,
        }
        self.poll_result: dict[str, Any] = {"status": "pending"}
        self.menu_supported = True
        self.notifications: list[FakeNotification] = []
        self.cards: list[dict[str, Any]] = []
        self.created_surface_count = 0
        self.connected = False
        self.reconnect_count = 0
        self._seen_cards: set[tuple[str, str]] = set()

    def begin_install(self) -> dict[str, Any]:
        return dict(self.begin_result)

    def poll_install(self, session: str = "install-1") -> dict[str, Any]:
        del session
        result = dict(self.poll_result)
        if result.get("status") in {"expired", "timeout", "denied"}:
            result.setdefault("failure_code", "DEVICE_FLOW_EXPIRED")
        return result

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def reconnect(self) -> None:
        self.reconnect_count += 1
        self.connected = True

    def emit_text(
        self,
        adapter: Any,
        *,
        event_id: str,
        chat_id: str,
        sender_id: str,
        text: str,
        thread_id: str | None = None,
    ) -> Any:
        """Send a decoded text event through an injected adapter."""
        from omnigent.integrations.lark.protocol import LarkMessage

        return adapter.receive(LarkMessage(event_id, chat_id, thread_id, text, sender_id))

    def emit_card(
        self,
        adapter: Any,
        *,
        event_id: str,
        action_id: str,
        nonce: str,
        chat_id: str,
        actor_id: str,
        value: dict[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> Any:
        from omnigent.integrations.lark.protocol import LarkCardAction

        key = (action_id, nonce)
        self._seen_cards.add(key)
        action = LarkCardAction(
            event_id, action_id, nonce, chat_id, thread_id, actor_id, value or {}
        )
        return adapter.receive(action)

    def notify(self, kind: str, run_id: str, **payload: Any) -> None:
        self.notifications.append(FakeNotification(kind, run_id, payload))

    def has_notification(self, kind: str, run_id: str) -> bool:
        return any(item.kind == kind and item.run_id == run_id for item in self.notifications)

    def ensure_surface(self, installation_id: str) -> dict[str, Any]:
        """Provision once, falling back to a persistent card when menus fail."""
        del installation_id
        if self.cards:
            return self.cards[0]
        self.created_surface_count += 1
        surface = "menu" if self.menu_supported else "persistent_card"
        result = {
            "status": "active" if self.menu_supported else "partial",
            "surface_type": surface,
        }
        self.cards.append(result)
        return result
