"""Authenticated provider-neutral Run projection API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request, Response

from omnigent.entities.run_projection import Run, RunCreate, RunStatus
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runs.service import RunService
from omnigent.runs.session_gateway import ASGISessionGateway
from omnigent.runtime import pending_elicitations
from omnigent.server.auth import RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import CreateRunRequest, RunInspectorResponse
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore


def create_runs_router(
    store: SqlAlchemyRunStore,
    service: RunService,
    *,
    auth_provider: AuthProvider | None = None,
    session_gateway_factory: Callable[[Request], ASGISessionGateway] | None = None,
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
        gateway = session_gateway_factory(request) if session_gateway_factory is not None else None
        create_kwargs: dict[str, Any] = {
            "actor_id": actor_id,
            "auth_scope": f"user:{actor_id}",
        }
        if gateway is not None:
            create_kwargs.update(
                session_creator=gateway.create_root,
                session_input_sender=gateway.send_input,
            )
        result = await service.create(RunCreate(**body.model_dump()), **create_kwargs)
        response.status_code = 201 if result.created else 200
        return _run_payload(result.run)

    @router.get("/runs")
    async def list_runs(request: Request) -> dict[str, Any]:
        actor_id = require_user(request, auth_provider) or RESERVED_USER_LOCAL
        return {
            "object": "list",
            "data": [_run_payload(run) for run in store.list_runs(actor_id=actor_id)],
        }

    @router.get("/runs/{run_id}", response_model=RunInspectorResponse)
    async def get_run(request: Request, run_id: str) -> RunInspectorResponse:
        return _inspector_payload(request, run_id, store, auth_provider)

    @router.get("/runs/{run_id}/events")
    async def list_events(request: Request, run_id: str) -> dict[str, Any]:
        _owned_run(request, run_id, store, auth_provider)
        return {
            "object": "list",
            "data": [asdict(event) for event in store.list_projection_events(run_id)],
        }

    @router.get("/runs/{run_id}/inspector", response_model=RunInspectorResponse)
    async def inspect_run(request: Request, run_id: str) -> RunInspectorResponse:
        return _inspector_payload(request, run_id, store, auth_provider)

    @router.post("/runs/{run_id}/stop")
    async def stop_run(request: Request, run_id: str) -> dict[str, str]:
        run = _owned_run(request, run_id, store, auth_provider)
        if run.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            raise OmnigentError("Run is already terminal", code=ErrorCode.CONFLICT)
        if run.root_session_id is None:
            raise OmnigentError("Run has no Root Session", code=ErrorCode.CONFLICT)
        gateway = _session_gateway(request, session_gateway_factory)
        await gateway.stop(run.root_session_id)
        return {"id": run.id, "status": "stopping"}

    @router.post("/runs/{run_id}/approvals/{approval_id}/{decision}")
    async def decide_approval(
        request: Request,
        run_id: str,
        approval_id: str,
        decision: str,
    ) -> dict[str, str]:
        run = _owned_run(request, run_id, store, auth_provider)
        if decision not in {"approve", "deny"}:
            raise OmnigentError(
                "decision must be 'approve' or 'deny'",
                code=ErrorCode.INVALID_INPUT,
            )
        if run.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            raise OmnigentError("Run is already terminal", code=ErrorCode.CONFLICT)
        target_session_id = _pending_approval_session(store, run, approval_id)
        if target_session_id is None:
            raise OmnigentError("Pending approval not found", code=ErrorCode.NOT_FOUND)
        gateway = _session_gateway(request, session_gateway_factory)
        await gateway.decide_approval(target_session_id, approval_id, decision)
        return {"id": approval_id, "run_id": run.id, "decision": decision}

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


def _inspector_payload(
    request: Request,
    run_id: str,
    store: SqlAlchemyRunStore,
    auth_provider: AuthProvider | None,
) -> RunInspectorResponse:
    _owned_run(request, run_id, store, auth_provider)
    return RunInspectorResponse.model_validate(
        asdict(store.inspect_run(run_id)) | {"object": "run.inspector"}
    )


def _session_gateway(
    request: Request,
    factory: Callable[[Request], ASGISessionGateway] | None,
) -> ASGISessionGateway:
    if factory is None:
        raise OmnigentError(
            "Session control gateway is unavailable",
            code=ErrorCode.INTERNAL_ERROR,
        )
    return factory(request)


def _pending_approval_session(
    store: SqlAlchemyRunStore,
    run: Run,
    approval_id: str,
) -> str | None:
    inspector = store.inspect_run(run.id)
    session_ids = tuple(
        session_id
        for session_id in (run.root_session_id, *inspector.child_session_ids)
        if session_id is not None
    )
    for session_id in session_ids:
        for event in pending_elicitations.snapshot_for(session_id):
            if event.get("elicitation_id") != approval_id:
                continue
            params = event.get("params")
            target = params.get("target_session_id") if isinstance(params, dict) else None
            if isinstance(target, str) and target in session_ids:
                return target
            return session_id
    return None
