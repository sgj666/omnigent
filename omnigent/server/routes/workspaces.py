"""Workspace-bundle listing, creation, and per-thread selection routes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.routes.teams import TeamMemoryStore
from omnigent.server.schemas import CreateWorkspaceRequest, SelectWorkspaceRequest


def create_workspaces_router(
    store: TeamMemoryStore,
    *,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Build the workspace-bundle API backed by the shared team store."""
    router = APIRouter()

    @router.post("/workspaces")
    async def create_workspace(request: Request, body: CreateWorkspaceRequest) -> dict[str, Any]:
        require_user(request, auth_provider)
        workspace_id = uuid4().hex
        workspace = {
            "id": workspace_id,
            "object": "workspace",
            "root_path": body.root_path,
            "repositories": body.repositories,
        }
        store.workspaces[workspace_id] = workspace
        persist_workspace = getattr(store, "persist_workspace", None)
        if persist_workspace is not None:
            persist_workspace(workspace)
        return deepcopy(workspace)

    @router.get("/workspaces")
    async def list_workspaces(request: Request) -> dict[str, Any]:
        require_user(request, auth_provider)
        return {"object": "list", "data": [deepcopy(value) for value in store.workspaces.values()]}

    @router.post("/workspaces/{workspace_id}/select")
    async def select_workspace(
        request: Request, workspace_id: str, body: SelectWorkspaceRequest
    ) -> dict[str, Any]:
        require_user(request, auth_provider)
        workspace = store.workspaces.get(workspace_id)
        if workspace is None:
            raise OmnigentError("Workspace not found", code=ErrorCode.NOT_FOUND)
        if body.run_id is not None:
            run = store.runs.get(body.run_id)
            if run is None:
                raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
            if run["status"] == "running" and run["workspace_id"] != workspace_id:
                raise OmnigentError(
                    "Workspace is immutable while a run is running", code=ErrorCode.CONFLICT
                )
            run["workspace_id"] = workspace_id
        select_thread_workspace = getattr(store, "select_thread_workspace", None)
        if select_thread_workspace is None:
            store.thread_workspaces[body.thread_id] = workspace_id
        else:
            select_thread_workspace(body.thread_id, workspace_id)
        return {
            "object": "workspace.selection",
            "thread_id": body.thread_id,
            "workspace": deepcopy(workspace),
        }

    return router
