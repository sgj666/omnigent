"""REST API routes for projects (``/v1/projects``).

Projects are first-class, owner-private containers that group sessions (see
``designs/PROJECTS_PRD.md``). These endpoints let the web UI create empty
projects, list them, rename them, and delete them. Session membership
(filing a session into a project) is managed on the sessions API via the
conversation store's ``project_id``.

Because projects are owner-private and carry no ACL of their own, every handler
scopes to the requesting user: a caller only ever sees and mutates their own
projects. In single-user mode (no auth provider) the owner is ``None`` and all
projects share that scope.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Request

from omnigent.entities import Project
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.project_artifacts import list_project_artifacts
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import (
    CreateProjectRequest,
    UpdateProjectRequest,
)
from omnigent.stores.file_store import FileStore
from omnigent.stores.project_store import ProjectStore
from omnigent.stores.work_item_run_store import WorkItemRunStore
from omnigent.stores.work_item_store import WorkItemStore


def _to_response(
    project: Project,
    *,
    session_count: int | None = None,
    artifact_count: int | None = None,
    latest_artifact_name: str | None = None,
    latest_artifact_at: int | None = None,
) -> dict[str, Any]:
    """Convert a :class:`Project` entity to a ``ProjectObject`` response dict.

    :param project: The entity to convert.
    :returns: Dict matching the :class:`ProjectObject` shape.
    """
    response = {
        "id": project.id,
        "object": "project",
        "name": project.name,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "config": project.config,
    }
    if session_count is not None:
        response["session_count"] = session_count
    if artifact_count is not None:
        response.update(
            {
                "artifact_count": artifact_count,
                "latest_artifact_name": latest_artifact_name,
                "latest_artifact_at": latest_artifact_at,
            }
        )
    return response


def create_projects_router(
    project_store: ProjectStore,
    *,
    file_store: FileStore | None = None,
    work_item_store: WorkItemStore | None = None,
    work_item_run_store: WorkItemRunStore | None = None,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Build the projects router (``/v1/projects``).

    :param project_store: The store backing project persistence.
    :param auth_provider: Auth provider used to identify the requesting user.
        ``None`` in single-user mode (owner scope is ``None``).
    :returns: A configured :class:`APIRouter`.
    """
    router = APIRouter()

    @router.post("/projects")
    async def create_project(
        request: Request,
        body: CreateProjectRequest,
    ) -> dict[str, Any]:
        """Create a new, empty project owned by the caller.

        :param request: The incoming request, used to identify the user.
        :param body: Project payload (name).
        :returns: The created project as a serialized dict.
        :raises OmnigentError: 401 if unauthenticated in multi-user mode, 409
            if the caller already has a project with this name.
        """
        user_id = require_user(request, auth_provider)
        project = await asyncio.to_thread(
            project_store.create,
            uuid.uuid4().hex,
            body.name,
            user_id,
            body.config,
        )
        return _to_response(project)

    @router.get("/projects")
    async def list_projects(request: Request) -> dict[str, Any]:
        """List the caller's projects.

        :param request: The incoming request, used to identify the user.
        :returns: ``{"object": "list", "data": [...]}``.
        :raises OmnigentError: 401 if unauthenticated in multi-user mode.
        """
        user_id = require_user(request, auth_provider)
        projects = await asyncio.to_thread(project_store.list, owner_user_id=user_id)
        counts = await asyncio.to_thread(
            project_store.count_sessions,
            [project.id for project in projects],
        )
        artifact_summaries: dict[str, tuple[int, str | None, int | None]] = {}
        if (
            file_store is not None
            and work_item_store is not None
            and work_item_run_store is not None
        ):
            artifact_lists = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        list_project_artifacts,
                        project.id,
                        owner_user_id=user_id,
                        work_item_store=work_item_store,
                        work_item_run_store=work_item_run_store,
                        file_store=file_store,
                    )
                    for project in projects
                )
            )
            artifact_summaries = {
                project.id: (
                    len(artifacts),
                    artifacts[0]["name"] if artifacts else None,
                    artifacts[0]["created_at"] if artifacts else None,
                )
                for project, artifacts in zip(projects, artifact_lists, strict=True)
            }
        return {
            "object": "list",
            "data": [
                _to_response(
                    project,
                    session_count=counts.get(project.id, 0),
                    artifact_count=(
                        artifact_summaries[project.id][0]
                        if project.id in artifact_summaries
                        else None
                    ),
                    latest_artifact_name=(
                        artifact_summaries[project.id][1]
                        if project.id in artifact_summaries
                        else None
                    ),
                    latest_artifact_at=(
                        artifact_summaries[project.id][2]
                        if project.id in artifact_summaries
                        else None
                    ),
                )
                for project in projects
            ],
        }

    @router.get("/projects/{project_id}")
    async def get_project(request: Request, project_id: str) -> dict[str, Any]:
        """Return one of the caller's projects.

        :param request: The incoming request, used to identify the user.
        :param project_id: The project to fetch.
        :returns: The project as a serialized dict.
        :raises OmnigentError: 401 if unauthenticated, 404 if not found / not
            owned by the caller.
        """
        user_id = require_user(request, auth_provider)
        project = await asyncio.to_thread(project_store.get, project_id, owner_user_id=user_id)
        if project is None:
            raise OmnigentError("Project not found", code=ErrorCode.NOT_FOUND)
        counts = await asyncio.to_thread(project_store.count_sessions, [project.id])
        return _to_response(project, session_count=counts.get(project.id, 0))

    if file_store is not None and work_item_store is not None and work_item_run_store is not None:

        @router.get("/projects/{project_id}/artifacts")
        async def list_artifacts(request: Request, project_id: str) -> dict[str, Any]:
            """List real TaskRun output files associated with one Project."""
            user_id = require_user(request, auth_provider)
            project = await asyncio.to_thread(
                project_store.get,
                project_id,
                owner_user_id=user_id,
            )
            if project is None:
                raise OmnigentError("Project not found", code=ErrorCode.NOT_FOUND)
            artifacts = await asyncio.to_thread(
                list_project_artifacts,
                project_id,
                owner_user_id=user_id,
                work_item_store=work_item_store,
                work_item_run_store=work_item_run_store,
                file_store=file_store,
            )
            return {"object": "list", "data": artifacts}

    @router.patch("/projects/{project_id}")
    async def update_project(
        request: Request,
        project_id: str,
        body: UpdateProjectRequest,
    ) -> dict[str, Any]:
        """Update one of the caller's projects (e.g. rename).

        :param request: The incoming request, used to identify the user.
        :param project_id: The project to update.
        :param body: Fields to change; ``None`` fields are left unchanged.
        :returns: The updated project as a serialized dict.
        :raises OmnigentError: 401 if unauthenticated, 404 if not found / not
            owned, 409 if the new name collides with another of the caller's
            projects.
        """
        user_id = require_user(request, auth_provider)
        project = await asyncio.to_thread(
            project_store.update,
            project_id,
            owner_user_id=user_id,
            name=body.name,
            config=body.config,
        )
        if project is None:
            raise OmnigentError("Project not found", code=ErrorCode.NOT_FOUND)
        return _to_response(project)

    @router.delete("/projects/{project_id}")
    async def delete_project(request: Request, project_id: str) -> dict[str, Any]:
        """Delete one of the caller's projects.

        Member sessions are preserved and unfiled atomically with the project.

        :param request: The incoming request, used to identify the user.
        :param project_id: The project to delete.
        :returns: ``{"id": ..., "object": "project.deleted", "deleted": True}``.
        :raises OmnigentError: 401 if unauthenticated, 404 if not found / not
            owned by the caller.
        """
        user_id = require_user(request, auth_provider)
        deleted = await asyncio.to_thread(project_store.delete, project_id, owner_user_id=user_id)
        if not deleted:
            raise OmnigentError("Project not found", code=ErrorCode.NOT_FOUND)
        return {"id": project_id, "object": "project.deleted", "deleted": True}

    return router
