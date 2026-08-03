"""Small, transport-independent helpers for Feishu/Lark event envelopes."""

# Provider payloads are intentionally untyped; the decoder is the type boundary.
# mypy: disable-error-code=explicit-any

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class LarkProtocolError(ValueError):
    """An event was malformed or failed protocol validation."""


@dataclass(frozen=True)
class LarkMessage:
    event_id: str
    chat_id: str
    thread_id: str | None
    text: str
    sender_id: str
    mentions: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class LarkCardAction:
    event_id: str
    action_id: str
    nonce: str
    chat_id: str
    thread_id: str | None
    actor_id: str
    value: Mapping[str, Any] = field(default_factory=dict)
    signature: str | None = None
    timestamp: str | None = None


def _obj(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LarkProtocolError("event must be an object")
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


def _text(content: object) -> str:
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except (TypeError, ValueError):
            return content
        if isinstance(decoded, Mapping):
            if decoded.get("text"):
                return str(decoded["text"])
            locale = decoded.get("zh_cn")
            if isinstance(locale, Mapping):
                return str(locale.get("text", locale.get("content", "")))
            if isinstance(locale, list):
                return " ".join(str(item) for item in locale)
        return content
    if isinstance(content, Mapping):
        return str(content.get("text", ""))
    return ""


def decode_message(payload: Mapping[str, Any]) -> LarkMessage:
    """Decode ``im.message.receive_v1`` from either a raw or wrapped envelope."""
    envelope = _obj(payload)
    header = _obj(envelope.get("header", {}))
    event = _obj(envelope.get("event", envelope))
    message = _obj(event.get("message", event))
    chat_id = message.get("chat_id")
    if not isinstance(chat_id, str) or not chat_id:
        raise LarkProtocolError("message is missing chat_id")
    sender = _obj(event.get("sender", message.get("sender", {})))
    sender_id = _identity(sender.get("sender_id") or sender)
    if sender_id is None:
        raise LarkProtocolError("message is missing sender id")
    mentions_raw = message.get("mentions", event.get("mentions", ()))
    mentions: list[str] = []
    if isinstance(mentions_raw, (list, tuple)):
        for mention in mentions_raw:
            if isinstance(mention, Mapping):
                value = mention.get("key") or mention.get("id") or mention.get("name")
            else:
                value = mention
            found = _identity(value)
            if found:
                mentions.append(found)
    event_id = header.get("event_id") or envelope.get("event_id") or message.get("message_id")
    if not isinstance(event_id, str) or not event_id:
        raise LarkProtocolError("message is missing event_id")
    return LarkMessage(
        event_id=event_id,
        chat_id=chat_id,
        thread_id=message.get("thread_id") or message.get("root_id"),
        text=_text(message.get("content", event.get("content", ""))),
        sender_id=sender_id,
        mentions=tuple(mentions),
        raw=envelope,
    )


def decode_card_action(payload: Mapping[str, Any]) -> LarkCardAction:
    """Decode ``card.action.trigger`` and retain the signed action values."""
    envelope = _obj(payload)
    header = _obj(envelope.get("header", {}))
    event = _obj(envelope.get("event", envelope))
    action = _obj(event.get("action", envelope.get("action", {})))
    value = action.get("value", {})
    if not isinstance(value, Mapping):
        raise LarkProtocolError("card action value must be an object")
    action_id = action.get("action_id") or value.get("action_id")
    nonce = action.get("nonce") or value.get("nonce")
    if not isinstance(action_id, str) or not action_id:
        raise LarkProtocolError("card action is missing action_id")
    if not isinstance(nonce, str) or not nonce:
        raise LarkProtocolError("card action is missing nonce")
    actor = _obj(event.get("operator", event.get("user", {})))
    actor_id = _identity(actor.get("operator_id") or actor)
    if actor_id is None:
        raise LarkProtocolError("card action is missing actor id")
    context = _obj(event.get("context", {}))
    chat_id = (
        event.get("chat_id")
        or context.get("chat_id")
        or context.get("open_chat_id")
        or value.get("chat_id")
    )
    if not isinstance(chat_id, str) or not chat_id:
        raise LarkProtocolError("card action is missing chat_id")
    event_id = header.get("event_id") or envelope.get("event_id") or f"{action_id}:{nonce}"
    return LarkCardAction(
        event_id=str(event_id),
        action_id=action_id,
        nonce=nonce,
        chat_id=chat_id,
        thread_id=(event.get("thread_id") or context.get("thread_id")
                   or context.get("open_thread_id") or value.get("thread_id")),
        actor_id=actor_id,
        value=dict(value),
        signature=action.get("signature") or envelope.get("signature"),
        timestamp=str(action.get("timestamp") or envelope.get("timestamp"))
        if (action.get("timestamp") or envelope.get("timestamp")) is not None
        else None,
    )


def decode_event(payload: Mapping[str, Any] | bytes | str) -> LarkMessage | LarkCardAction:
    """Dispatch decoding using the provider's event type discriminator."""
    if isinstance(payload, bytes | str):
        payload = json.loads(payload)
    header = payload.get("header", {})
    event_type = header.get("event_type") if isinstance(header, Mapping) else None
    event = payload.get("event", {})
    if event_type == "card.action.trigger" or (
        isinstance(event, Mapping) and "action" in event
    ):
        return decode_card_action(payload)
    return decode_message(payload)


def verify_signature(
    *, timestamp: str, nonce: str, body: str | bytes, secret: str, signature: str
) -> bool:
    """Verify Feishu's ``sha256(timestamp + nonce + encrypt_key + body)`` signature."""
    raw = body if isinstance(body, bytes) else body.encode()
    expected = hashlib.sha256(
        timestamp.encode() + nonce.encode() + secret.encode() + raw
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
