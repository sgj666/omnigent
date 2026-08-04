"""External Run creation backed exclusively by real Session execution."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

from omnigent.entities import AgentBundleSnapshot
from omnigent.entities.run_projection import CreateRunResult, RunCreate
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.schemas import SessionEventInput

SOURCE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")


class _RunStore(Protocol):
    def get_workspace(self, workspace_id: str) -> Any | None: ...

    def create_run_idempotent(self, **kwargs: Any) -> CreateRunResult: ...


class _ConversationStore(Protocol):
    def create_conversation(self, **kwargs: Any) -> Any: ...


class _AgentStore(Protocol):
    def get(self, agent_id: str) -> Any | None: ...


SubmitSessionEvent = Callable[[str, SessionEventInput, str], Awaitable[None]]


class RunService:
    """Create a pinned Root Coordinator Session and submit its first input."""

    def __init__(
        self,
        *,
        run_store: _RunStore,
        conversation_store: _ConversationStore,
        agent_store: _AgentStore,
        submit_session_event: SubmitSessionEvent,
    ) -> None:
        self._runs = run_store
        self._conversations = conversation_store
        self._agents = agent_store
        self._submit_session_event = submit_session_event

    async def create(
        self,
        command: RunCreate,
        *,
        actor_id: str,
        auth_scope: str,
    ) -> CreateRunResult:
        if SOURCE_RE.fullmatch(command.source) is None:
            raise OmnigentError(
                "source must match [a-z][a-z0-9_.-]{0,63}",
                code=ErrorCode.INVALID_INPUT,
            )
        workspace = self._runs.get_workspace(command.workspace_id)
        if workspace is None:
            raise OmnigentError(
                f"Workspace not found: {command.workspace_id!r}",
                code=ErrorCode.NOT_FOUND,
            )
        agent = self._agents.get(command.agent_id)
        if agent is None:
            raise OmnigentError(
                f"Agent not found: {command.agent_id!r}",
                code=ErrorCode.NOT_FOUND,
            )
        try:
            snapshot = AgentBundleSnapshot.from_agent(agent)
        except ValueError as exc:
            raise OmnigentError(
                f"Run Agent has no valid content-addressed Bundle snapshot: {exc}",
                code=ErrorCode.CONFLICT,
            ) from exc

        root_session_id = uuid4().hex
        result = self._runs.create_run_idempotent(
            auth_scope=auth_scope,
            actor_id=actor_id,
            source=command.source,
            source_event_id=command.source_event_id,
            agent_id=agent.id,
            bundle_version=snapshot.bundle_version,
            bundle_digest=snapshot.bundle_digest,
            bundle_location=snapshot.bundle_location,
            workspace_id=workspace.id,
            root_session_id=root_session_id,
        )
        if not result.created:
            return result

        self._conversations.create_conversation(
            conversation_id=root_session_id,
            kind="default",
            title=command.title or "Run coordinator",
            agent_id=agent.id,
            workspace=workspace.root_path,
            agent_bundle_version=snapshot.bundle_version,
            agent_bundle_digest=snapshot.bundle_digest,
            agent_bundle_location=snapshot.bundle_location,
        )
        event = SessionEventInput(
            type="message",
            data={
                "role": "user",
                "content": [{"type": "input_text", "text": command.prompt}],
            },
        )
        await self._submit_session_event(root_session_id, event, actor_id)
        return result
