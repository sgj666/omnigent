"""Authenticated provider-neutral Run projection API."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request, Response

from omnigent.entities.run_projection import Run, RunCreate
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runs.service import RunService
from omnigent.server.auth import RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import CreateRunRequest
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore


def create_runs_router(
    store: SqlAlchemyRunStore,
    service: RunService,
    *,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Build the only external Run creation and inspection boundary."""
    router = APIRouter()

    @router.post("/runs", status_code=201)
    async def create_run(
        request: Request,
        response: Response,
        body: CreateRunRequest,
    ) -> dict[str, Any]:
        actor_id = require_user(request, auth_provider) or RESERVED_USER_LOCAL
        result = await service.create(
            RunCreate(**body.model_dump()),
            actor_id=actor_id,
            auth_scope=f"user:{actor_id}",
        )
        response.status_code = 201 if result.created else 200
        return _run_payload(result.run)

    @router.get("/runs")
    async def list_runs(request: Request) -> dict[str, Any]:
        actor_id = require_user(request, auth_provider) or RESERVED_USER_LOCAL
        return {
            "object": "list",
            "data": [_run_payload(run) for run in store.list_runs(actor_id=actor_id)],
        }

    @router.get("/runs/{run_id}")
    async def get_run(request: Request, run_id: str) -> dict[str, Any]:
        return _run_payload(_owned_run(request, run_id, store, auth_provider))

    @router.get("/runs/{run_id}/events")
    async def list_events(request: Request, run_id: str) -> dict[str, Any]:
        _owned_run(request, run_id, store, auth_provider)
        return {
            "object": "list",
            "data": [asdict(event) for event in store.list_projection_events(run_id)],
        }

    @router.get("/runs/{run_id}/inspector")
    async def inspect_run(request: Request, run_id: str) -> dict[str, Any]:
        _owned_run(request, run_id, store, auth_provider)
        return asdict(store.inspect_run(run_id)) | {"object": "run.inspector"}

    return router


def _owned_run(
    request: Request,
    run_id: str,
    store: SqlAlchemyRunStore,
    auth_provider: AuthProvider | None,
) -> Run:
    actor_id = require_user(request, auth_provider) or RESERVED_USER_LOCAL
    run = store.get_run(run_id)
    if run is None or run.actor_id != actor_id:
        raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
    return run


def _run_payload(run: Run) -> dict[str, Any]:
    return asdict(run) | {"object": "run"}
