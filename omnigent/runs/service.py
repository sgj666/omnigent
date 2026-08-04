"""External Run creation backed exclusively by real Session execution."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from omnigent.entities import AgentBundleSnapshot
from omnigent.entities.run_projection import CreateRunResult, RunCreate, RunStatus
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runs.session_projection import SessionRunProjection
from omnigent.server.schemas import SessionEventInput

SOURCE_RE = re.compile(r"^[a-z][a-z0-9_-]*(?::[a-z0-9_-]+)?$")


class _RunStore(Protocol):
    def get_workspace(self, workspace_id: str) -> Any | None: ...

    def list_workspaces(self) -> tuple[Any, ...]: ...

    def create_run_idempotent(self, **kwargs: Any) -> CreateRunResult: ...

    def bind_root_session(self, run_id: str, root_session_id: str) -> Any: ...

    def mark_run_started(self, run_id: str) -> Any: ...

    def mark_run_creation_failed(self, run_id: str, *, code: str, message: str) -> Any: ...

    def get_run_creation_failure(self, run_id: str) -> Any | None: ...


class _ConversationStore(Protocol):
    def create_conversation(self, **kwargs: Any) -> Any: ...


class _AgentStore(Protocol):
    def get(self, agent_id: str) -> Any | None: ...


@dataclass(frozen=True)
class RootSessionRequest:
    """Provider-neutral input for the existing Session creation gateway."""

    agent_id: str
    workspace: str
    host_id: str | None
    execution_mode: str
    bundle_version: int
    bundle_digest: str
    bundle_location: str


SessionCreator = Callable[[RootSessionRequest, str], Awaitable[str]]
SessionInputSender = Callable[[str, SessionEventInput, str], Awaitable[None]]
SessionCleaner = Callable[[str, str], Awaitable[None]]

_logger = logging.getLogger(__name__)


class RunService:
    """Create a pinned Root Coordinator Session and submit its first input."""

    def __init__(
        self,
        *,
        run_store: _RunStore,
        conversation_store: _ConversationStore,
        agent_store: _AgentStore,
        submit_session_event: SessionInputSender,
        session_creator: SessionCreator | None = None,
        session_cleaner: SessionCleaner | None = None,
    ) -> None:
        self._runs = run_store
        self._conversations = conversation_store
        self._agents = agent_store
        self._submit_session_event = submit_session_event
        self._session_creator = session_creator
        self._session_cleaner = session_cleaner
        self._projection = SessionRunProjection(run_store)

    async def create(
        self,
        command: RunCreate,
        *,
        actor_id: str,
        auth_scope: str,
        session_creator: SessionCreator | None = None,
        session_input_sender: SessionInputSender | None = None,
        session_cleaner: SessionCleaner | None = None,
    ) -> CreateRunResult:
        if SOURCE_RE.fullmatch(command.source) is None:
            raise OmnigentError(
                "source must match ^[a-z][a-z0-9_-]*(?::[a-z0-9_-]+)?$",
                code=ErrorCode.INVALID_INPUT,
            )
        workspace = self._resolve_workspace(command.workspace_id)
        workspace_id = command.workspace_id or (workspace.id if workspace is not None else None)
        if workspace is None:
            raise OmnigentError(
                f"Workspace not found: {workspace_id!r}",
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
            root_session_id=None,
        )
        if not result.created:
            if result.run.status is RunStatus.CREATING:
                raise OmnigentError(
                    "Run creation is already in progress for this external event",
                    code=ErrorCode.CONFLICT,
                )
            if result.run.status is RunStatus.FAILED:
                failure = self._runs.get_run_creation_failure(result.run.id)
                detail = f" ({failure.code}: {failure.message})" if failure is not None else ""
                raise OmnigentError(
                    f"Run creation previously failed for this external event{detail}",
                    code=ErrorCode.CONFLICT,
                )
            if result.run.root_session_id is None:
                raise OmnigentError(
                    "Run has no Root Session",
                    code=ErrorCode.CONFLICT,
                )
            return result

        create_root = session_creator or self._session_creator or self._create_root_legacy
        send_input = session_input_sender or self._submit_session_event
        cleanup = session_cleaner or self._session_cleaner
        stage = "root_session_create"
        root_session_id: str | None = None
        try:
            root_session_id = await create_root(
                RootSessionRequest(
                    agent_id=agent.id,
                    workspace=workspace.root_path,
                    host_id=command.host_id,
                    execution_mode=command.execution_mode,
                    bundle_version=snapshot.bundle_version,
                    bundle_digest=snapshot.bundle_digest,
                    bundle_location=snapshot.bundle_location,
                ),
                actor_id,
            )
            bound_run = self._runs.bind_root_session(result.run.id, root_session_id)
            self._projection.root_created(bound_run)
            stage = "root_input_submit"
            event = SessionEventInput(
                type="message",
                data={
                    "role": "user",
                    "content": [{"type": "input_text", "text": command.input}],
                },
            )
            await send_input(root_session_id, event, actor_id)
            started = self._runs.mark_run_started(result.run.id)
        except Exception as exc:
            code = exc.code if isinstance(exc, OmnigentError) else ErrorCode.INTERNAL_ERROR
            message = (
                "Root Session creation failed"
                if stage == "root_session_create"
                else "Root Session input was not accepted"
            )
            self._runs.mark_run_creation_failed(result.run.id, code=code, message=message)
            if root_session_id is not None and cleanup is not None:
                try:
                    await cleanup(root_session_id, actor_id)
                except Exception:
                    _logger.exception(
                        "Failed to clean Root Session after Run creation failure: "
                        "run=%s session=%s",
                        result.run.id,
                        root_session_id,
                    )
            raise
        return CreateRunResult(run=started, created=True)

    def _resolve_workspace(self, workspace_id: str | None) -> Any | None:
        if workspace_id is not None:
            return self._runs.get_workspace(workspace_id)
        workspaces = self._runs.list_workspaces()
        if len(workspaces) == 1:
            return workspaces[0]
        if not workspaces:
            raise OmnigentError("No default workspace is available", code=ErrorCode.NOT_FOUND)
        raise OmnigentError(
            "workspace_id is required when more than one workspace is available",
            code=ErrorCode.CONFLICT,
        )

    async def _create_root_legacy(self, request: RootSessionRequest, _actor_id: str) -> str:
        """Compatibility seam for focused tests; production injects the Session API gateway."""
        created = self._conversations.create_conversation(
            kind="default",
            title="Run coordinator",
            agent_id=request.agent_id,
            host_id=request.host_id,
            workspace=request.workspace,
            agent_bundle_version=request.bundle_version,
            agent_bundle_digest=request.bundle_digest,
            agent_bundle_location=request.bundle_location,
        )
        session_id = getattr(created, "id", None)
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("Root Session allocation returned no session id")
        return session_id
