"""Owner-private product Task routes under ``/v1/work-items``."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, Request

from omnigent.entities import WorkItem, WorkItemRun
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.native_coding_agents import native_coding_agent_for_agent_name
from omnigent.runs.service import TaskSessionRequest
from omnigent.runs.session_gateway import ASGISessionGateway
from omnigent.runtime import user_session_stream
from omnigent.server import session_live_state
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import (
    CreateWorkItemRequest,
    CreateWorkItemRunRequest,
    SessionEventInput,
    UpdateWorkItemRequest,
)
from omnigent.stores import AgentStore
from omnigent.stores.conversation_store import ConversationStore
from omnigent.stores.project_store import ProjectStore
from omnigent.stores.work_item_run_store import WorkItemRunStore
from omnigent.stores.work_item_store import WorkItemStore
from omnigent.work_lifecycle import TaskRunState, TaskRunTrigger


def _to_response(item: WorkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "object": "work_item",
        "title": item.title,
        "description": item.description,
        "state": item.state.value,
        "priority": item.priority,
        "project_id": item.project_id,
        "assignee_agent_id": item.assignee_agent_id,
        "due_at": item.due_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "completed_at": item.completed_at,
        "creator_kind": item.creator_kind,
        "created_by_agent_id": item.created_by_agent_id,
        "version": item.version,
    }


def _run_response(run: WorkItemRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "object": "work_item_run",
        "work_item_id": run.work_item_id,
        "session_id": run.session_id,
        "agent_id": run.agent_id,
        "runtime_id": run.runtime_id,
        "workspace": run.workspace,
        "state": run.state.value,
        "trigger": run.trigger.value,
        "retry_of_run_id": run.retry_of_run_id,
        "queued_at": run.queued_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "updated_at": run.updated_at,
        "result_summary": run.result_summary,
        "failure": (
            {
                "code": run.failure_code,
                "message": run.failure_message,
                "retryable": run.failure_retryable,
            }
            if run.failure_code is not None and run.failure_message is not None
            else None
        ),
        "artifact_refs": run.artifact_refs,
        "usage_refs": run.usage_refs,
    }


def _task_prompt(item: WorkItem) -> str:
    prompt = f"Task: {item.title}"
    if item.description:
        prompt += f"\n\nDescription:\n{item.description}"
    return prompt + "\n\nComplete this task and summarize the result in this session."


def _publish_changed(owner_user_id: str | None) -> None:
    user_session_stream.publish(
        user_session_stream.user_key(owner_user_id),
        {"type": "work_items_changed"},
    )


async def _require_project(
    project_store: ProjectStore | None,
    project_id: str | None,
    owner_user_id: str | None,
) -> None:
    if project_id is None:
        return
    project = (
        await asyncio.to_thread(project_store.get, project_id, owner_user_id=owner_user_id)
        if project_store is not None
        else None
    )
    if project is None:
        raise OmnigentError("Project not found", code=ErrorCode.NOT_FOUND)


def create_work_items_router(
    work_item_store: WorkItemStore,
    *,
    work_item_run_store: WorkItemRunStore | None = None,
    agent_store: AgentStore | None = None,
    conversation_store: ConversationStore | None = None,
    project_store: ProjectStore | None = None,
    auth_provider: AuthProvider | None = None,
    session_gateway_factory: Callable[[Request], ASGISessionGateway] | None = None,
) -> APIRouter:
    """Create the WorkItem CRUD router."""

    router = APIRouter()

    @router.post("/work-items")
    async def create_work_item(
        request: Request,
        body: CreateWorkItemRequest,
        x_orvia_creator_agent_id: str | None = Header(default=None),
        x_orvia_creator_session_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        user_id = require_user(request, auth_provider)
        await _require_project(project_store, body.project_id, user_id)
        creator_kind = "user"
        if x_orvia_creator_agent_id is not None:
            creator = (
                await asyncio.to_thread(agent_store.get, x_orvia_creator_agent_id)
                if agent_store is not None
                else None
            )
            if creator is None:
                raise OmnigentError("Creator Agent not found", code=ErrorCode.NOT_FOUND)
            if x_orvia_creator_session_id is None:
                raise OmnigentError(
                    "Creator Session is required for Agent-created Tasks",
                    code=ErrorCode.INVALID_INPUT,
                )
            creator_session = (
                await asyncio.to_thread(
                    conversation_store.get_conversation,
                    x_orvia_creator_session_id,
                )
                if conversation_store is not None
                else None
            )
            if creator_session is None:
                raise OmnigentError("Creator Session not found", code=ErrorCode.NOT_FOUND)
            if creator_session.agent_id != x_orvia_creator_agent_id:
                raise OmnigentError(
                    "Creator Session does not belong to the Creator Agent",
                    code=ErrorCode.FORBIDDEN,
                )
            if creator_session.parent_conversation_id is not None:
                raise OmnigentError(
                    "Only the multi-Agent coordinator can create or assign Tasks",
                    code=ErrorCode.FORBIDDEN,
                )
            creator_kind = "agent"
        assignee_agent_id = body.assignee_agent_id or x_orvia_creator_agent_id
        if assignee_agent_id is not None and assignee_agent_id != x_orvia_creator_agent_id:
            assignee = (
                await asyncio.to_thread(agent_store.get, assignee_agent_id)
                if agent_store is not None
                else None
            )
            if assignee is None:
                raise OmnigentError("Assignee Agent not found", code=ErrorCode.NOT_FOUND)
        item = await asyncio.to_thread(
            work_item_store.create,
            uuid.uuid4().hex,
            owner_user_id=user_id,
            title=body.title,
            description=body.description,
            state=body.state,
            priority=body.priority,
            project_id=body.project_id,
            assignee_agent_id=assignee_agent_id,
            due_at=body.due_at,
            creator_kind=creator_kind,
            created_by_agent_id=x_orvia_creator_agent_id,
        )
        _publish_changed(user_id)
        return _to_response(item)

    @router.get("/work-items")
    async def list_work_items(request: Request) -> dict[str, Any]:
        user_id = require_user(request, auth_provider)
        items = await asyncio.to_thread(work_item_store.list, owner_user_id=user_id)
        return {"object": "list", "data": [_to_response(item) for item in items]}

    if work_item_run_store is not None and agent_store is not None:

        @router.get("/work-items/{work_item_id}/runs")
        async def list_work_item_runs(request: Request, work_item_id: str) -> dict[str, Any]:
            user_id = require_user(request, auth_provider)
            item = await asyncio.to_thread(
                work_item_store.get, work_item_id, owner_user_id=user_id
            )
            if item is None:
                raise OmnigentError("Task not found", code=ErrorCode.NOT_FOUND)
            runs = await asyncio.to_thread(
                work_item_run_store.list_for_work_item,
                work_item_id,
                owner_user_id=user_id,
            )
            return {"object": "list", "data": [_run_response(run) for run in runs]}

        @router.get("/work-items/{work_item_id}/runs/{run_id}")
        async def get_work_item_run(
            request: Request, work_item_id: str, run_id: str
        ) -> dict[str, Any]:
            user_id = require_user(request, auth_provider)
            run = await asyncio.to_thread(work_item_run_store.get, run_id, owner_user_id=user_id)
            if run is None or run.work_item_id != work_item_id:
                raise OmnigentError("TaskRun not found", code=ErrorCode.NOT_FOUND)
            return _run_response(run)

        @router.post("/work-items/{work_item_id}/runs", status_code=201)
        async def create_work_item_run(
            request: Request,
            work_item_id: str,
            body: CreateWorkItemRunRequest,
        ) -> dict[str, Any]:
            user_id = require_user(request, auth_provider)
            item = await asyncio.to_thread(
                work_item_store.get, work_item_id, owner_user_id=user_id
            )
            if item is None:
                raise OmnigentError("Task not found", code=ErrorCode.NOT_FOUND)
            if item.assignee_agent_id is None:
                raise OmnigentError(
                    "Assign an Agent before starting this Task",
                    code=ErrorCode.CONFLICT,
                )
            agent = await asyncio.to_thread(agent_store.get, item.assignee_agent_id)
            if agent is None:
                raise OmnigentError(
                    "The assigned Agent is no longer available",
                    code=ErrorCode.CONFLICT,
                )

            trigger = TaskRunTrigger.MANUAL
            if body.retry_of_run_id is not None:
                previous = await asyncio.to_thread(
                    work_item_run_store.get,
                    body.retry_of_run_id,
                    owner_user_id=user_id,
                )
                if previous is None or previous.work_item_id != item.id:
                    raise OmnigentError("Retry TaskRun not found", code=ErrorCode.NOT_FOUND)
                if previous.state not in {TaskRunState.FAILED, TaskRunState.CANCELLED}:
                    raise OmnigentError(
                        "Only failed or cancelled TaskRuns can be retried",
                        code=ErrorCode.CONFLICT,
                    )
                trigger = TaskRunTrigger.RETRY

            run = await asyncio.to_thread(
                work_item_run_store.create,
                uuid.uuid4().hex,
                work_item_id=item.id,
                owner_user_id=user_id,
                agent_id=agent.id,
                runtime_id=body.runtime_id,
                workspace=body.workspace,
                trigger=trigger.value,
                retry_of_run_id=body.retry_of_run_id,
            )
            gateway = (
                session_gateway_factory(request)
                if session_gateway_factory is not None
                else ASGISessionGateway(request)
            )
            native_agent = native_coding_agent_for_agent_name(agent.name)
            labels = native_agent.presentation_labels if native_agent is not None else {}
            try:
                session_id = await gateway.create_task_session(
                    TaskSessionRequest(
                        agent_id=agent.id,
                        title=f"Task · {item.title}",
                        project_id=item.project_id,
                        runtime_id=body.runtime_id,
                        workspace=body.workspace,
                        labels=labels,
                    )
                )
                bound = await asyncio.to_thread(
                    work_item_run_store.bind_session,
                    run.id,
                    owner_user_id=user_id,
                    session_id=session_id,
                )
                if bound is None:
                    raise RuntimeError("TaskRun disappeared before Session binding")
                await gateway.send_input(
                    session_id,
                    SessionEventInput(
                        type="message",
                        data={
                            "role": "user",
                            "content": [{"type": "input_text", "text": _task_prompt(item)}],
                        },
                    ),
                    user_id or "local",
                )
                run = await asyncio.to_thread(
                    work_item_run_store.transition,
                    run.id,
                    state=TaskRunState.RUNNING.value,
                )
            except Exception as exc:  # noqa: BLE001 - failed launches remain audited
                code = exc.code if isinstance(exc, OmnigentError) else ErrorCode.INTERNAL_ERROR
                message = exc.message if isinstance(exc, OmnigentError) else str(exc)
                run = await asyncio.to_thread(
                    work_item_run_store.transition,
                    run.id,
                    state=TaskRunState.FAILED.value,
                    failure_code=code,
                    failure_message=message or "TaskRun launch failed",
                    failure_retryable=code
                    in {
                        ErrorCode.INTERNAL_ERROR,
                        ErrorCode.RUNNER_UNAVAILABLE,
                        ErrorCode.RUNNER_CAPABILITY_MISMATCH,
                    },
                )
            if run is None:
                raise OmnigentError("TaskRun not found", code=ErrorCode.NOT_FOUND)
            if run.state in {TaskRunState.FAILED, TaskRunState.CANCELLED}:
                session_live_state.persist_work_item_run_terminal(run)
            return _run_response(run)

        @router.post("/work-items/{work_item_id}/runs/{run_id}/cancel")
        async def cancel_work_item_run(
            request: Request, work_item_id: str, run_id: str
        ) -> dict[str, Any]:
            user_id = require_user(request, auth_provider)
            run = await asyncio.to_thread(work_item_run_store.get, run_id, owner_user_id=user_id)
            if run is None or run.work_item_id != work_item_id:
                raise OmnigentError("TaskRun not found", code=ErrorCode.NOT_FOUND)
            if run.state in {
                TaskRunState.SUCCEEDED,
                TaskRunState.FAILED,
                TaskRunState.CANCELLED,
            }:
                raise OmnigentError("TaskRun is already terminal", code=ErrorCode.CONFLICT)
            if run.session_id is None:
                raise OmnigentError("TaskRun has no Session", code=ErrorCode.CONFLICT)
            gateway = (
                session_gateway_factory(request)
                if session_gateway_factory is not None
                else ASGISessionGateway(request)
            )
            await gateway.stop(run.session_id)
            cancelled = await asyncio.to_thread(
                work_item_run_store.transition,
                run.id,
                state=TaskRunState.CANCELLED.value,
            )
            if cancelled is None:
                raise OmnigentError("TaskRun not found", code=ErrorCode.NOT_FOUND)
            return _run_response(cancelled)

    @router.get("/work-items/{work_item_id}")
    async def get_work_item(request: Request, work_item_id: str) -> dict[str, Any]:
        user_id = require_user(request, auth_provider)
        item = await asyncio.to_thread(
            work_item_store.get,
            work_item_id,
            owner_user_id=user_id,
        )
        if item is None:
            raise OmnigentError("Task not found", code=ErrorCode.NOT_FOUND)
        return _to_response(item)

    @router.patch("/work-items/{work_item_id}")
    async def update_work_item(
        request: Request,
        work_item_id: str,
        body: UpdateWorkItemRequest,
    ) -> dict[str, Any]:
        user_id = require_user(request, auth_provider)
        changed_fields = body.model_fields_set - {"expected_version"}
        changes = {field: getattr(body, field) for field in changed_fields}
        if "project_id" in changes:
            await _require_project(project_store, changes["project_id"], user_id)
        item = await asyncio.to_thread(
            work_item_store.update,
            work_item_id,
            owner_user_id=user_id,
            expected_version=body.expected_version,
            changes=changes,
        )
        if item is None:
            raise OmnigentError("Task not found", code=ErrorCode.NOT_FOUND)
        if item.state.value == "done" and "state" in changes:
            session_live_state.persist_work_item_completed(item)
        _publish_changed(user_id)
        return _to_response(item)

    return router
