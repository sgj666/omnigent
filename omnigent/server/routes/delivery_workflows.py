"""Authenticated Delivery Workflow subresource of a provider-neutral Run."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from omnigent.delivery_workflow import DeliveryWorkflowService
from omnigent.entities.delivery_workflow import DeliveryPhase, DeliveryStatus
from omnigent.server.auth import RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import require_user

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class PlannedTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_key: NonEmpty
    title: NonEmpty
    owner_role: NonEmpty | None = None
    description: str | None = Field(default=None, max_length=20_000)
    task_kind: str = Field(default="delivery", pattern=r"^(requirement|delivery)$")
    parent_task_key: NonEmpty | None = None
    depends_on: list[NonEmpty] = Field(default_factory=list)
    artifact_requirements: list[NonEmpty] = Field(default_factory=list)


class PutDeliveryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    tasks: list[PlannedTaskInput]


class RegisterDeliveryArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NonEmpty
    location: NonEmpty
    content_sha256: Sha256
    planned_task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeliveryTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_phase: DeliveryPhase
    expected_version: int = Field(ge=1)
    to_phase: DeliveryPhase
    to_status: DeliveryStatus
    idempotency_key: NonEmpty
    evidence_refs: list[str] = Field(min_length=1)


class AssignDeliveryTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    worker_name: NonEmpty | None


def create_delivery_workflows_router(
    service: DeliveryWorkflowService,
    *,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    router = APIRouter()

    def current_run_id(
        request: Request,
        agent_id: str,
        session_id: str,
    ) -> str:
        return service.resolve_current_run_id(
            actor_id=_actor(request, auth_provider),
            workflow_agent_id=agent_id,
            workflow_session_id=session_id,
        )

    @router.get("/delivery-workflow")
    async def get_current_delivery_workflow(
        request: Request,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        run_id = current_run_id(
            request, x_orvia_workflow_agent_id, x_orvia_workflow_session_id
        )
        return _snapshot(
            service.get(
                run_id,
                actor_id=_actor(request, auth_provider),
                workflow_agent_id=x_orvia_workflow_agent_id,
                workflow_session_id=x_orvia_workflow_session_id,
            )
        )

    @router.put("/delivery-workflow/plan")
    async def put_current_delivery_plan(
        request: Request,
        body: PutDeliveryPlanRequest,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        run_id = current_run_id(
            request, x_orvia_workflow_agent_id, x_orvia_workflow_session_id
        )
        return _snapshot(
            service.put_plan(
                run_id,
                actor_id=_actor(request, auth_provider),
                workflow_agent_id=x_orvia_workflow_agent_id,
                workflow_session_id=x_orvia_workflow_session_id,
                expected_version=body.expected_version,
                tasks=(task.model_dump() for task in body.tasks),
            )
        )

    @router.get("/delivery-workflow/tasks/ready")
    async def get_ready_delivery_tasks(
        request: Request,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        run_id = current_run_id(
            request, x_orvia_workflow_agent_id, x_orvia_workflow_session_id
        )
        tasks = service.ready_tasks(
            run_id,
            actor_id=_actor(request, auth_provider),
            workflow_agent_id=x_orvia_workflow_agent_id,
            workflow_session_id=x_orvia_workflow_session_id,
        )
        return {"object": "list", "data": [_work_item(item) for item in tasks]}

    @router.patch("/delivery-workflow/tasks/{task_key}/assignment")
    async def assign_delivery_task(
        request: Request,
        task_key: str,
        body: AssignDeliveryTaskRequest,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        run_id = current_run_id(
            request, x_orvia_workflow_agent_id, x_orvia_workflow_session_id
        )
        return _work_item(
            service.assign_task(
                run_id,
                actor_id=_actor(request, auth_provider),
                workflow_agent_id=x_orvia_workflow_agent_id,
                workflow_session_id=x_orvia_workflow_session_id,
                task_key=task_key,
                expected_version=body.expected_version,
                worker_name=body.worker_name,
            )
        )

    @router.post("/delivery-workflow/artifacts", status_code=201)
    async def register_current_delivery_artifact(
        request: Request,
        body: RegisterDeliveryArtifactRequest,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        run_id = current_run_id(
            request, x_orvia_workflow_agent_id, x_orvia_workflow_session_id
        )
        artifact = service.add_artifact(
            run_id,
            actor_id=_actor(request, auth_provider),
            workflow_agent_id=x_orvia_workflow_agent_id,
            workflow_session_id=x_orvia_workflow_session_id,
            **body.model_dump(),
        )
        return asdict(artifact) | {"object": "delivery.artifact"}

    @router.post("/delivery-workflow/transitions")
    async def transition_current_delivery_workflow(
        request: Request,
        body: DeliveryTransitionRequest,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        run_id = current_run_id(
            request, x_orvia_workflow_agent_id, x_orvia_workflow_session_id
        )
        return _snapshot(
            service.transition(
                run_id,
                actor_id=_actor(request, auth_provider),
                workflow_agent_id=x_orvia_workflow_agent_id,
                workflow_session_id=x_orvia_workflow_session_id,
                **body.model_dump(),
            )
        )

    @router.get("/runs/{run_id}/delivery-workflow")
    async def get_delivery_workflow(
        request: Request,
        run_id: str,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        return _snapshot(
            service.get(
                run_id,
                actor_id=_actor(request, auth_provider),
                workflow_agent_id=x_orvia_workflow_agent_id,
                workflow_session_id=x_orvia_workflow_session_id,
            )
        )

    @router.put("/runs/{run_id}/delivery-workflow/plan")
    async def put_delivery_plan(
        request: Request,
        run_id: str,
        body: PutDeliveryPlanRequest,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        return _snapshot(
            service.put_plan(
                run_id,
                actor_id=_actor(request, auth_provider),
                workflow_agent_id=x_orvia_workflow_agent_id,
                workflow_session_id=x_orvia_workflow_session_id,
                expected_version=body.expected_version,
                tasks=(task.model_dump() for task in body.tasks),
            )
        )

    @router.post("/runs/{run_id}/delivery-workflow/artifacts", status_code=201)
    async def register_delivery_artifact(
        request: Request,
        run_id: str,
        body: RegisterDeliveryArtifactRequest,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        artifact = service.add_artifact(
            run_id,
            actor_id=_actor(request, auth_provider),
            workflow_agent_id=x_orvia_workflow_agent_id,
            workflow_session_id=x_orvia_workflow_session_id,
            **body.model_dump(),
        )
        return asdict(artifact) | {"object": "delivery.artifact"}

    @router.post("/runs/{run_id}/delivery-workflow/transitions")
    async def transition_delivery_workflow(
        request: Request,
        run_id: str,
        body: DeliveryTransitionRequest,
        x_orvia_workflow_agent_id: str = Header(),
        x_orvia_workflow_session_id: str = Header(),
    ) -> dict[str, Any]:
        return _snapshot(
            service.transition(
                run_id,
                actor_id=_actor(request, auth_provider),
                workflow_agent_id=x_orvia_workflow_agent_id,
                workflow_session_id=x_orvia_workflow_session_id,
                **body.model_dump(),
            )
        )

    return router


def _actor(request: Request, auth_provider: AuthProvider | None) -> str:
    return require_user(request, auth_provider) or RESERVED_USER_LOCAL


def _snapshot(value: Any) -> dict[str, Any]:
    return asdict(value) | {"object": "delivery.workflow"}


def _work_item(value: Any) -> dict[str, Any]:
    result = asdict(value)
    result["state"] = value.state.value
    result["object"] = "work_item"
    return result
