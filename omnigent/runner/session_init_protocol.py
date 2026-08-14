"""Versioned server-to-runner session initialization payloads."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from omnigent.entities import Agent, AgentBundleSnapshot, Conversation

SessionInitProtocolVersion: TypeAlias = Literal[2]
SESSION_INIT_PROTOCOL_VERSION: SessionInitProtocolVersion = 2
SESSION_INIT_PAYLOAD_KEY = "session_init"
RUN_CHILD_SANDBOX_OVERRIDE_LABEL = "omnigent.run_child.sandbox_override"


class RunnerSessionInitSnapshot(BaseModel):  # type: ignore[explicit-any]  # Pydantic uses Any
    """Server-owned session state needed while starting a runner session."""

    model_config = ConfigDict(extra="ignore")

    created_at: int
    updated_at: int
    workspace: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    reasoning_effort: str | None = None
    model_override: str | None = None
    harness_override: str | None = None
    cost_control_mode_override: str | None = None
    terminal_launch_args: list[str] | None = None
    external_session_id: str | None = None
    parent_session_id: str | None = None
    root_session_id: str | None = None


class RunnerSessionInitEnvelope(BaseModel):  # type: ignore[explicit-any]  # Pydantic uses Any
    """Metadata a current server can send instead of runner callback reads."""

    model_config = ConfigDict(extra="ignore")

    protocol_version: SessionInitProtocolVersion
    server_version: str
    session_id: str
    agent_id: str
    bundle_version: int
    bundle_digest: str
    bundle_location: str
    sub_agent_name: str | None = None
    snapshot: RunnerSessionInitSnapshot
    # When True the runner must skip crash-recovery turn detection on this
    # create_session call.  Set by the server whenever it calls session-init
    # immediately before forwarding a message — the forward carries the
    # message, so a recovery turn started from history would process it twice
    # (once from the recovery path, once from the buffered forward).
    suppress_recovery_turn: bool = False


def build_runner_session_init_payload(
    conversation: Conversation,
    *,
    server_version: str,
    suppress_recovery_turn: bool = False,
    agent: Agent | None = None,
) -> dict[str, object]:
    """Build the versioned initialization fields appended to the legacy body."""
    if conversation.agent_id is None:
        raise ValueError("runner session initialization requires an agent_id")
    bundle_fields = (
        conversation.agent_bundle_version,
        conversation.agent_bundle_digest,
        conversation.agent_bundle_location,
    )
    if all(value is None for value in bundle_fields):
        if agent is None or agent.id != conversation.agent_id:
            raise ValueError(
                "legacy runner session initialization requires the current bound Agent"
            )
        bundle_snapshot = AgentBundleSnapshot.from_agent(agent)
    else:
        if any(value is None for value in bundle_fields):
            raise ValueError(
                "runner session initialization requires a complete agent bundle snapshot"
            )
        bundle_snapshot = AgentBundleSnapshot(
            agent_id=conversation.agent_id,
            bundle_version=conversation.agent_bundle_version,
            bundle_digest=conversation.agent_bundle_digest,
            bundle_location=conversation.agent_bundle_location,
        )
    envelope = RunnerSessionInitEnvelope(
        protocol_version=SESSION_INIT_PROTOCOL_VERSION,
        server_version=server_version,
        session_id=conversation.id,
        agent_id=conversation.agent_id,
        bundle_version=bundle_snapshot.bundle_version,
        bundle_digest=bundle_snapshot.bundle_digest,
        bundle_location=bundle_snapshot.bundle_location,
        sub_agent_name=conversation.sub_agent_name,
        suppress_recovery_turn=suppress_recovery_turn,
        snapshot=RunnerSessionInitSnapshot(
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            workspace=conversation.workspace,
            labels=conversation.labels,
            reasoning_effort=conversation.reasoning_effort,
            model_override=conversation.model_override,
            harness_override=conversation.harness_override,
            cost_control_mode_override=conversation.cost_control_mode_override,
            terminal_launch_args=conversation.terminal_launch_args,
            external_session_id=conversation.external_session_id,
            parent_session_id=conversation.parent_conversation_id,
            root_session_id=conversation.root_conversation_id,
        ),
    )
    return {
        "session_id": conversation.id,
        "agent_id": conversation.agent_id,
        "sub_agent_name": conversation.sub_agent_name,
        SESSION_INIT_PAYLOAD_KEY: envelope.model_dump(mode="json"),
    }


def parse_runner_session_init_envelope(
    body: dict[str, object],
) -> RunnerSessionInitEnvelope | None:
    """Return a supported envelope, or ``None`` for the removable legacy path."""
    raw = body.get(SESSION_INIT_PAYLOAD_KEY)
    if not isinstance(raw, dict):
        return None
    if raw.get("protocol_version") != SESSION_INIT_PROTOCOL_VERSION:
        return None
    try:
        return RunnerSessionInitEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("invalid runner session initialization envelope") from exc
