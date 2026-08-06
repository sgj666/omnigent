"""Pure Feishu envelope decoding, challenge, and signature validation."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class FeishuProtocolError(ValueError):
    """An untrusted provider envelope is malformed or unauthenticated."""


@dataclass(frozen=True)
class FeishuMessage:
    event_id: str
    chat_id: str
    thread_id: str | None
    text: str
    sender_id: str
    mentions: tuple[str, ...] = ()
    chat_type: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class FeishuCardAction:
    event_id: str
    action_id: str
    nonce: str
    chat_id: str
    thread_id: str | None
    sender_id: str
    value: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeishuMenuAction:
    event_id: str
    event_key: str
    sender_id: str


def verify_signature(
    *, timestamp: str, nonce: str, body: str | bytes, secret: str, signature: str
) -> bool:
    raw = body if isinstance(body, bytes) else body.encode()
    expected = hashlib.sha256(
        timestamp.encode() + nonce.encode() + secret.encode() + raw
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def challenge_response(
    payload: Mapping[str, Any], verification_token: str | None
) -> dict[str, str] | None:
    challenge = payload.get("challenge")
    if challenge is None:
        return None
    token = payload.get("token")
    if verification_token is not None and not hmac.compare_digest(str(token), verification_token):
        raise FeishuProtocolError("challenge verification failed")
    if not isinstance(challenge, str) or not challenge:
        raise FeishuProtocolError("invalid challenge")
    return {"challenge": challenge}


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FeishuProtocolError(message)
    return value


def _identity(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        for key in ("open_id", "user_id", "id", "key"):
            found = _identity(value.get(key))
            if found:
                return found
    return None


def _content_text(value: object) -> str:
    if isinstance(value, Mapping):
        direct = value.get("text")
        if isinstance(direct, str):
            return direct
        parts = [_content_text(item) for item in value.values()]
        return "\n".join(part for part in parts if part)
    if isinstance(value, list):
        parts = [_content_text(item) for item in value]
        return "".join(parts)
    if not isinstance(value, str):
        return ""
    try:
        decoded = json.loads(value)
    except ValueError:
        return value
    return _content_text(decoded)


def decode_message(payload: Mapping[str, Any]) -> FeishuMessage:
    header = _mapping(payload.get("header", {}), "invalid event header")
    event = _mapping(payload.get("event", payload), "invalid event")
    message = _mapping(event.get("message", event), "invalid message")
    event_id = header.get("event_id") or payload.get("event_id") or message.get("message_id")
    chat_id = message.get("chat_id")
    sender = _mapping(event.get("sender", message.get("sender", {})), "invalid sender")
    sender_id = _identity(sender.get("sender_id") or sender)
    if not isinstance(event_id, str) or not event_id:
        raise FeishuProtocolError("message is missing event_id")
    if not isinstance(chat_id, str) or not chat_id:
        raise FeishuProtocolError("message is missing chat_id")
    if sender_id is None:
        raise FeishuProtocolError("message is missing sender id")
    mentions: list[str] = []
    raw_mentions = message.get("mentions", ())
    if isinstance(raw_mentions, list):
        for mention in raw_mentions:
            found = _identity(mention)
            if found:
                mentions.append(found)
    return FeishuMessage(
        event_id=event_id,
        chat_id=chat_id,
        thread_id=message.get("thread_id") or message.get("root_id"),
        text=_content_text(message.get("content", "")),
        sender_id=sender_id,
        mentions=tuple(mentions),
        chat_type=message.get("chat_type"),
        raw=payload,
    )


def decode_card_action(payload: Mapping[str, Any]) -> FeishuCardAction:
    header = _mapping(payload.get("header", {}), "invalid event header")
    event = _mapping(payload.get("event", payload), "invalid event")
    action = _mapping(event.get("action", payload.get("action", {})), "invalid action")
    value = _mapping(action.get("value", {}), "invalid action value")
    action_id = action.get("action_id") or value.get("action_id")
    nonce = action.get("nonce") or value.get("nonce")
    sender_id = _identity(event.get("operator") or event.get("user"))
    context = event.get("context", {})
    context = context if isinstance(context, Mapping) else {}
    chat_id = event.get("chat_id") or context.get("open_chat_id") or value.get("chat_id")
    if not all(isinstance(item, str) and item for item in (action_id, nonce, sender_id, chat_id)):
        raise FeishuProtocolError("card action is incomplete")
    event_id = header.get("event_id") or payload.get("event_id") or f"{action_id}:{nonce}"
    return FeishuCardAction(
        event_id=str(event_id),
        action_id=str(action_id),
        nonce=str(nonce),
        chat_id=str(chat_id),
        thread_id=(
            event.get("thread_id") or context.get("open_thread_id") or value.get("thread_id")
        ),
        sender_id=str(sender_id),
        value=dict(value),
    )


def decode_menu_action(payload: Mapping[str, Any]) -> FeishuMenuAction:
    header = _mapping(payload.get("header", {}), "invalid event header")
    event = _mapping(payload.get("event", payload), "invalid menu event")
    operator = _mapping(event.get("operator", {}), "invalid menu operator")
    event_id = header.get("event_id") or payload.get("event_id")
    event_key = event.get("event_key")
    sender_id = _identity(operator.get("operator_id") or operator)
    if not isinstance(event_id, str) or not event_id:
        raise FeishuProtocolError("menu event is missing event_id")
    if not isinstance(event_key, str) or not event_key:
        raise FeishuProtocolError("menu event is missing event_key")
    if sender_id is None:
        raise FeishuProtocolError("menu event is missing operator")
    return FeishuMenuAction(event_id, event_key, sender_id)


def decode_event(
    payload: Mapping[str, Any] | bytes | str,
) -> FeishuMessage | FeishuCardAction | FeishuMenuAction:
    if isinstance(payload, bytes | str):
        decoded = json.loads(payload)
        payload = _mapping(decoded, "event must be an object")
    header = payload.get("header", {})
    event_type = header.get("event_type") if isinstance(header, Mapping) else None
    event = payload.get("event", {})
    if event_type in {"application.bot.menu_v6", "p2.application.bot.menu_v6"}:
        return decode_menu_action(payload)
    if event_type == "card.action.trigger" or (isinstance(event, Mapping) and "action" in event):
        return decode_card_action(payload)
    return decode_message(payload)


LarkMessage = FeishuMessage
LarkCardAction = FeishuCardAction
LarkMenuAction = FeishuMenuAction
LarkProtocolError = FeishuProtocolError

__all__ = [
    "FeishuCardAction",
    "FeishuMenuAction",
    "FeishuMessage",
    "FeishuProtocolError",
    "challenge_response",
    "decode_card_action",
    "decode_event",
    "decode_menu_action",
    "decode_message",
    "verify_signature",
]
