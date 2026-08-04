"""Authenticated owner-scoped Run evaluation routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from fastapi import APIRouter, Request

from omnigent.entities.run_evaluation import EvaluationRecord
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.auth import RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.run_evaluation_schemas import (
    EvaluateRunRequest,
    RunEvaluationResponse,
    evaluation_response,
)


class EvaluationService(Protocol):
    def get_or_evaluate(self, run_id: str, *, owner_user_id: str) -> EvaluationRecord: ...

    def evaluate(
        self,
        run_id: str,
        *,
        owner_user_id: str,
        refresh: bool = False,
    ) -> EvaluationRecord: ...


OwnerCheck = Callable[[str, str], bool]


def create_run_evaluations_router(
    service: EvaluationService,
    *,
    auth_provider: AuthProvider | None = None,
    owner_check: OwnerCheck | None = None,
) -> APIRouter:
    """Build the isolated evaluation API without wiring Core Run execution."""
    router = APIRouter()

    def owned_actor(request: Request, run_id: str) -> str:
        actor_id = require_user(request, auth_provider) or RESERVED_USER_LOCAL
        if owner_check is not None and not owner_check(run_id, actor_id):
            raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
        return actor_id

    @router.get("/runs/{run_id}/evaluation", response_model=RunEvaluationResponse)
    async def get_run_evaluation(request: Request, run_id: str) -> RunEvaluationResponse:
        actor_id = owned_actor(request, run_id)
        return evaluation_response(service.get_or_evaluate(run_id, owner_user_id=actor_id))

    @router.post("/runs/{run_id}/evaluation", response_model=RunEvaluationResponse)
    async def evaluate_run(
        request: Request,
        run_id: str,
        body: EvaluateRunRequest,
    ) -> RunEvaluationResponse:
        actor_id = owned_actor(request, run_id)
        return evaluation_response(
            service.evaluate(run_id, owner_user_id=actor_id, refresh=body.refresh)
        )

    return router
