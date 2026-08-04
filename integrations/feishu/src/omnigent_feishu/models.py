"""Provider-state records; Core execution entities remain opaque IDs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Installation:
    id: str
    agent_id: str
    app_id: str | None
    app_secret_ciphertext: str | None
    installer_open_id: str | None
    bot_open_id: str | None
    status: str
    device_session: str | None
    verification_uri: str | None
    error: str | None
    created_at: int
    updated_at: int
    verification_uri_base: str | None
    user_code: str | None
    interval: int | None
    expires_at: int | None
    expires_in: int | None
    tenant_key: str | None
    tenant_name: str | None
    bot_name: str | None
    bot_avatar_url: str | None


@dataclass(frozen=True)
class ThreadBinding:
    id: str
    installation_id: str
    chat_id: str
    thread_id: str
    agent_id: str
    workspace_id: str | None
    run_id: str | None
    host_id: str | None
    execution_mode: str
    allowed_members: tuple[str, ...]


@dataclass(frozen=True)
class InboundEvent:
    event_id: str
    installation_id: str
    sender_id: str | None
    status: str
    run_id: str | None
    error_code: str | None


@dataclass(frozen=True)
class Notification:
    id: str
    installation_id: str
    run_id: str | None
    event_id: str | None
    payload: str
    status: str
    attempt_count: int
    next_attempt_at: int
    last_error: str | None


__all__ = ["InboundEvent", "Installation", "Notification", "ThreadBinding"]
