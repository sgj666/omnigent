"""Inbound Lark adapter with validation, deduplication and retry seams."""

# Transport clients and provider JSON are intentionally duck-typed.
# mypy: disable-error-code=explicit-any

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .protocol import (
    LarkCardAction,
    LarkMessage,
    LarkProtocolError,
    decode_card_action,
    decode_message,
    verify_signature,
)
from .router import LarkRouter, LarkRoutingError


@dataclass(frozen=True)
class AdapterResult:
    result: Any
    duplicate: bool = False
    diagnostic: str | None = None


class MemoryDeduper:
    """Bounded, injectable deduper; replace with a durable idempotency store."""

    def __init__(self) -> None:
        self._items: dict[str, float] = {}

    def claim(self, key: str, *, ttl: int = 600) -> bool:
        now = time.time()
        self._items = {item: expiry for item, expiry in self._items.items() if expiry > now}
        if key in self._items:
            return False
        self._items[key] = now + ttl
        return True


class LarkAdapter:
    """Translate provider events into Coordinator requests only."""

    def __init__(self, router: LarkRouter | None = None, *, signing_secret: str | None = None,
                 nonce_ttl: int = 600, sender: Any = None, deduper: Any = None,
                 signature_ttl: int = 300) -> None:
        self.router = router or LarkRouter()
        self.signing_secret = signing_secret
        self.nonce_ttl = nonce_ttl
        self.signature_ttl = signature_ttl
        self.sender = sender
        self.deduper = deduper or MemoryDeduper()
        self._seen_events: dict[str, AdapterResult] = {}
        self._seen_actions: dict[tuple[str, str], AdapterResult] = {}
        self._seen_nonces: set[tuple[str, str]] = set()
        self.connected = False
        self.reconnect_count = 0

    def _validate_signature(self, payload: Mapping[str, Any], action: LarkCardAction) -> None:
        if self.signing_secret is None:
            return
        signature = action.signature or payload.get("signature")
        timestamp = action.timestamp or str(payload.get("timestamp", ""))
        if not isinstance(signature, str) or not timestamp:
            raise LarkRoutingError("invalid_signature", "Card action has no signature")
        try:
            if abs(time.time() - float(timestamp)) > self.signature_ttl:
                raise LarkRoutingError("invalid_signature", "Card action signature expired")
        except ValueError as exc:
            raise LarkRoutingError(
                "invalid_signature", "Card action timestamp is invalid"
            ) from exc
        body = payload.get("body", payload)
        encoded = (
            body
            if isinstance(body, str)
            else json.dumps(body, separators=(",", ":"), sort_keys=True)
        )
        if not verify_signature(timestamp=timestamp, nonce=action.nonce, body=encoded,
                                secret=self.signing_secret, signature=signature):
            raise LarkRoutingError(
                "invalid_signature", "Card action signature verification failed"
            )

    def _validate_message_signature(self, payload: Mapping[str, Any]) -> None:
        if self.signing_secret is None:
            return
        header = payload.get("header", {})
        signature = payload.get("signature")
        timestamp = payload.get("timestamp")
        nonce = payload.get("nonce")
        if isinstance(header, Mapping):
            signature = signature or header.get("signature")
            timestamp = timestamp or header.get("timestamp")
            nonce = nonce or header.get("nonce")
        if not all(isinstance(value, str) and value for value in (signature, timestamp, nonce)):
            raise LarkRoutingError("invalid_signature", "Message has no signature")
        try:
            expired = abs(time.time() - float(timestamp)) > self.signature_ttl
        except ValueError as exc:
            raise LarkRoutingError("invalid_signature", "Message timestamp is invalid") from exc
        if expired:
            raise LarkRoutingError("invalid_signature", "Message signature expired")
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        if not verify_signature(timestamp=timestamp, nonce=nonce, body=encoded,
                                secret=self.signing_secret, signature=signature):
            raise LarkRoutingError("invalid_signature", "Message signature verification failed")

    def _claim(self, key: str) -> bool:
        try:
            return bool(self.deduper.claim(key, ttl=self.nonce_ttl))
        except TypeError:
            return bool(self.deduper.claim("lark", key))

    def receive(self, payload: Mapping[str, Any] | bytes | str | LarkMessage | LarkCardAction,
                *, headers: Mapping[str, str] | None = None) -> AdapterResult:
        """Process one decoded or raw event; replay returns the original result."""
        try:
            if isinstance(payload, LarkMessage):
                event: LarkMessage | LarkCardAction = payload
            elif isinstance(payload, LarkCardAction):
                event = payload
            else:
                if isinstance(payload, bytes | str):
                    decoded = json.loads(payload)
                    payload = decoded
                header = payload.get("header", {})
                event_type = (
                    str(header.get("event_type", payload.get("event_type", "")))
                    if isinstance(header, Mapping)
                    else str(payload.get("event_type", ""))
                )
                event_payload = payload.get("event", {})
                has_action = isinstance(event_payload, Mapping) and "action" in event_payload
                event = (
                    decode_card_action(payload)
                    if event_type == "card.action.trigger" or has_action
                    else decode_message(payload)
                )
        except (LarkProtocolError, TypeError, ValueError, KeyError) as exc:
            return AdapterResult(None, diagnostic=f"protocol: {exc}")
        event_id = event.event_id
        if event_id in self._seen_events:
            prior = self._seen_events[event_id]
            return AdapterResult(prior.result, duplicate=True, diagnostic=prior.diagnostic)
        try:
            if isinstance(event, LarkMessage):
                if isinstance(payload, Mapping):
                    if headers:
                        payload = dict(payload)
                        payload.setdefault(
                            "signature",
                            headers.get("X-Lark-Signature")
                            or headers.get("X-Las-Signature"),
                        )
                        payload.setdefault("timestamp", headers.get("X-Lark-Timestamp"))
                        payload.setdefault("nonce", headers.get("X-Lark-Nonce"))
                    self._validate_message_signature(payload)
                if not self._claim(f"event:{event.event_id}"):
                    prior = self._seen_events.get(event.event_id)
                    return AdapterResult(prior.result if prior else None, duplicate=True)
                result = self.router.route_message(event)
            else:
                raw = payload if isinstance(payload, Mapping) else {}
                if headers:
                    raw = dict(raw)
                    raw.setdefault("signature", headers.get("X-Lark-Signature"))
                    raw.setdefault("timestamp", headers.get("X-Lark-Timestamp"))
                self._validate_signature(raw, event)
                nonce_key = (event.action_id, event.nonce)
                if nonce_key in self._seen_actions or not self._claim(
                    f"action:{event.action_id}:{event.nonce}"
                ):
                    prior = self._seen_actions[nonce_key]
                    response = AdapterResult(
                        prior.result, duplicate=True, diagnostic=prior.diagnostic
                    )
                    self._seen_events[event_id] = response
                    return response
                self._seen_nonces.add(nonce_key)
                result = self.router.route_action(event)
            response = AdapterResult(result)
            if isinstance(event, LarkCardAction):
                self._seen_actions[(event.action_id, event.nonce)] = response
        except LarkRoutingError as exc:
            response = AdapterResult(None, diagnostic=f"{exc.code}: {exc}")
        self._seen_events[event_id] = response
        return response

    async def send_with_retry(self, message: Mapping[str, Any], *, attempts: int = 3,
                              delay: float = 0.05) -> Any:
        """Send through an injected client, retrying transient failures."""
        if self.sender is None:
            return message
        last: Exception | None = None
        for index in range(max(1, attempts)):
            try:
                result = self.sender(message)
                return await result if inspect.isawaitable(result) else result
            except (OSError, RuntimeError, TimeoutError) as exc:
                last = exc
                if index + 1 < attempts:
                    await asyncio.sleep(delay * (index + 1))
        assert last is not None
        raise last

    async def update_card(self, card: Mapping[str, Any], *, attempts: int = 3) -> Any:
        """Update a card while explicitly enabling Feishu multi-update semantics."""
        payload = dict(card)
        payload["update_multi"] = True
        return await self.send_with_retry(payload, attempts=attempts)

    def heartbeat(self) -> Mapping[str, str]:
        return {"type": "ping"}

    async def start(self) -> None:
        self.on_connect()

    async def close(self) -> None:
        self.connected = False

    def on_connect(self) -> None:
        self.connected = True

    def on_disconnect(self) -> int:
        self.connected = False
        self.reconnect_count += 1
        return self.reconnect_count

    def reconnect_delay(self) -> float:
        """Exponential reconnect backoff capped for a bounded reconnect loop."""
        return min(30.0, 0.5 * (2 ** max(0, self.reconnect_count - 1)))


__all__ = ["AdapterResult", "LarkAdapter"]
