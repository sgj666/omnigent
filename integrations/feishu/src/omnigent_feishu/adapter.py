"""Webhook dispatch, durable deduplication, and notification retry orchestration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from omnigent_feishu.protocol import (
    FeishuCardAction,
    FeishuProtocolError,
    challenge_response,
    decode_event,
    verify_signature,
)
from omnigent_feishu.router import FeishuRouter, RouteResult
from omnigent_feishu.store import FeishuStore


class NotificationTransport(Protocol):
    async def send(self, installation_id: str, payload: Mapping[str, object]) -> None: ...


@dataclass(frozen=True)
class AdapterResult:
    response: object
    duplicate: bool = False


class FeishuAdapter:
    def __init__(
        self,
        router: FeishuRouter,
        store: FeishuStore,
        *,
        verification_token: str | None = None,
        signature_secret: str | None = None,
    ) -> None:
        self._router = router
        self._store = store
        self._verification_token = verification_token
        self._signature_secret = signature_secret

    async def receive(
        self,
        raw: bytes,
        headers: Mapping[str, str],
        *,
        installation_id: str,
    ) -> AdapterResult:
        try:
            payload = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise FeishuProtocolError("invalid JSON envelope") from exc
        if not isinstance(payload, Mapping):
            raise FeishuProtocolError("event must be an object")
        challenge = challenge_response(payload, self._verification_token)
        if challenge is not None:
            return AdapterResult(challenge)
        if self._verification_token is not None:
            header = payload.get("header", {})
            token = header.get("token") if isinstance(header, Mapping) else None
            token = token or payload.get("token")
            if token != self._verification_token:
                raise FeishuProtocolError("verification token mismatch")
        if self._signature_secret is not None:
            timestamp = headers.get("x-lark-request-timestamp") or headers.get(
                "x-lark-timestamp", ""
            )
            nonce = headers.get("x-lark-request-nonce") or headers.get("x-lark-nonce", "")
            signature = headers.get("x-lark-signature", "")
            if not all((timestamp, nonce, signature)) or not verify_signature(
                timestamp=timestamp,
                nonce=nonce,
                body=raw,
                secret=self._signature_secret,
                signature=signature,
            ):
                raise FeishuProtocolError("signature verification failed")
        event = decode_event(payload)
        routed: RouteResult
        if isinstance(event, FeishuCardAction):
            routed = await self._router.route_action(event, installation_id)
        else:
            routed = await self._router.route(event, installation_id)
        return AdapterResult(
            {"event_id": routed.event_id, "run_id": routed.run_id},
            duplicate=routed.duplicate,
        )

    async def notify(
        self,
        *,
        installation_id: str,
        run_id: str,
        event_id: str,
        payload: Mapping[str, object],
    ) -> None:
        await self._store.enqueue_notification(
            installation_id=installation_id,
            run_id=run_id,
            event_id=event_id,
            payload=payload,
        )

    async def deliver_due(self, transport: NotificationTransport, *, limit: int = 20) -> int:
        delivered = 0
        for notification in await self._store.due_notifications(limit=limit):
            try:
                payload = json.loads(notification.payload)
                await transport.send(notification.installation_id, payload)
            except Exception:  # noqa: BLE001 - delivery is observable, never Run authority
                await self._store.retry_notification(notification.id, "provider delivery failed")
                continue
            await self._store.mark_notification_sent(notification.id)
            delivered += 1
        return delivered


__all__ = ["AdapterResult", "FeishuAdapter", "NotificationTransport"]
