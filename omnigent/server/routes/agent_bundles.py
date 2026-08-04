"""Independent provider-neutral Agent Bundle editing router."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Callable, Mapping
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile

from omnigent.agent_bundles.service import (
    AgentBundleService,
    BundleDetail,
    BundleValidationFailure,
)
from omnigent.harness_plugins import harness_catalog
from omnigent.server.auth import AuthProvider
from omnigent.server.bundle_schemas import (
    BundleAgentResponse,
    BundleCardResponse,
    BundleCloneRequest,
    BundleCreateRequest,
    BundleDetailResponse,
    BundleListResponse,
    BundleOptionsResponse,
    BundleUpdateRequest,
    BundleValidateRequest,
    BundleValidationIssueResponse,
    BundleValidationResponse,
    BundleWorkerCreateRequest,
    BundleWorkerDeleteRequest,
    BundleWorkerOrderRequest,
    BundleWorkerUpdateRequest,
)
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.routes._content_type import require_json_content_type
from omnigent.server.routes._origin import require_trusted_origin
from omnigent.stores.agent_store import AgentVersionConflict

OptionsProvider = Callable[[], Mapping[str, Any]]


def _default_options() -> Mapping[str, Any]:
    return {
        "harnesses": harness_catalog(),
        "models": [],
        "tools": [],
        "skills": [],
        "mcp": [],
        "environment": [],
    }


def _translate_error(exc: Exception) -> NoReturn:
    if isinstance(exc, BundleValidationFailure):
        issues = [
            BundleValidationIssueResponse.model_validate(issue).model_dump()
            for issue in exc.issues
        ]
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_bundle", "issues": issues},
        ) from None
    if isinstance(exc, AgentVersionConflict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "version_conflict",
                "expected": exc.expected,
                "actual": exc.actual,
            },
        ) from None
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail={"code": "read_only"}) from None
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail={"code": "not_found"}) from None
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail={"code": "invalid_request"}) from None
    raise exc


async def _call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return await asyncio.to_thread(method, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - translate the service boundary centrally
        _translate_error(exc)


def _config_dump(config: Any) -> dict[str, Any]:
    return config.model_dump(exclude_unset=True, by_alias=True)


def _detail_response(detail: BundleDetail) -> BundleDetailResponse:
    return BundleDetailResponse(
        card=BundleCardResponse.model_validate(detail.card),
        coordinator=BundleAgentResponse(
            name=detail.coordinator.name,
            config=detail.coordinator.config,
            advanced_yaml=detail.coordinator.advanced_yaml,
        ),
        workers=[
            BundleAgentResponse(
                name=worker.name,
                config=worker.config,
                advanced_yaml=worker.advanced_yaml,
            )
            for worker in detail.workers
        ],
    )


def create_agent_bundles_router(
    service: AgentBundleService,
    *,
    auth_provider: AuthProvider | None = None,
    options_provider: OptionsProvider | None = None,
) -> APIRouter:
    """Build the standalone router, intended for mounting under ``/v1``."""
    router = APIRouter()
    provide_options = options_provider or _default_options

    def authenticate(request: Request) -> None:
        require_user(request, auth_provider)

    @router.get("/agent-bundles", response_model=BundleListResponse)
    async def list_bundles(
        request: Request,
        limit: int = 20,
        after: str | None = None,
        before: str | None = None,
        order: str = "desc",
    ) -> BundleListResponse:
        authenticate(request)
        page = await _call(
            service.list,
            limit=limit,
            after=after,
            before=before,
            order=order,
        )
        return BundleListResponse(
            data=[BundleCardResponse.model_validate(card) for card in page.data],
            first_id=page.first_id,
            last_id=page.last_id,
        )

    # Static routes precede /{agent_id} so metadata is never interpreted as an ID.
    @router.get("/agent-bundles/options", response_model=BundleOptionsResponse)
    async def bundle_options(request: Request) -> BundleOptionsResponse:
        authenticate(request)
        return BundleOptionsResponse.model_validate(await asyncio.to_thread(provide_options))

    @router.post(
        "/agent-bundles/validate",
        response_model=BundleValidationResponse,
        dependencies=[Depends(require_json_content_type)],
    )
    async def validate_bundle(
        request: Request,
        body: BundleValidateRequest,
    ) -> BundleValidationResponse:
        authenticate(request)
        try:
            bundle = base64.b64decode(body.bundle_base64, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_base64"},
            ) from None
        result = await _call(service.validate, bundle)
        return BundleValidationResponse(
            valid=result.valid,
            issues=[
                BundleValidationIssueResponse.model_validate(issue) for issue in result.issues
            ],
        )

    @router.post(
        "/agent-bundles/import",
        response_model=BundleCardResponse,
        status_code=201,
        dependencies=[Depends(require_trusted_origin)],
    )
    async def import_bundle(
        request: Request,
        bundle: Annotated[UploadFile, File()],
        name: Annotated[str | None, Form()] = None,
        description: Annotated[str | None, Form()] = None,
    ) -> BundleCardResponse:
        authenticate(request)
        bundle_bytes = await bundle.read()
        card = await _call(
            service.import_bundle,
            bundle_bytes,
            name=name,
            description=description,
        )
        return BundleCardResponse.model_validate(card)

    @router.post(
        "/agent-bundles",
        response_model=BundleCardResponse,
        status_code=201,
        dependencies=[Depends(require_json_content_type)],
    )
    async def create_bundle(
        request: Request,
        body: BundleCreateRequest,
    ) -> BundleCardResponse:
        authenticate(request)
        card = await _call(
            service.create,
            name=body.name,
            description=body.description,
            config=_config_dump(body.config),
        )
        return BundleCardResponse.model_validate(card)

    @router.get("/agent-bundles/{agent_id}", response_model=BundleDetailResponse)
    async def get_bundle(request: Request, agent_id: str) -> BundleDetailResponse:
        authenticate(request)
        return _detail_response(await _call(service.get, agent_id))

    @router.put(
        "/agent-bundles/{agent_id}",
        response_model=BundleDetailResponse,
        dependencies=[Depends(require_json_content_type)],
    )
    async def update_bundle(
        request: Request,
        agent_id: str,
        body: BundleUpdateRequest,
    ) -> BundleDetailResponse:
        authenticate(request)
        changes = (
            _config_dump(body.coordinator_changes)
            if body.coordinator_changes is not None
            else None
        )
        detail = await _call(
            service.update,
            agent_id,
            expected_version=body.expected_version,
            coordinator_changes=changes,
            advanced_yaml=body.advanced_yaml,
            name=body.name,
            description=body.description,
        )
        return _detail_response(detail)

    @router.delete("/agent-bundles/{agent_id}", status_code=204)
    async def delete_bundle(request: Request, agent_id: str) -> Response:
        authenticate(request)
        await _call(service.delete, agent_id)
        return Response(status_code=204)

    @router.post(
        "/agent-bundles/{agent_id}/clone",
        response_model=BundleCardResponse,
        status_code=201,
        dependencies=[Depends(require_json_content_type)],
    )
    async def clone_bundle(
        request: Request,
        agent_id: str,
        body: BundleCloneRequest,
    ) -> BundleCardResponse:
        authenticate(request)
        card = await _call(
            service.clone,
            agent_id,
            name=body.name,
            description=body.description,
        )
        return BundleCardResponse.model_validate(card)

    @router.get("/agent-bundles/{agent_id}/export")
    async def export_bundle(request: Request, agent_id: str) -> Response:
        authenticate(request)
        bundle_bytes = await _call(service.export, agent_id)
        return Response(
            content=bundle_bytes,
            media_type="application/gzip",
            headers={"Content-Disposition": 'attachment; filename="agent-bundle.tar.gz"'},
        )

    @router.get(
        "/agent-bundles/{agent_id}/workers",
        response_model=list[BundleAgentResponse],
    )
    async def list_workers(request: Request, agent_id: str) -> list[BundleAgentResponse]:
        authenticate(request)
        detail = await _call(service.get, agent_id)
        return [
            BundleAgentResponse(
                name=worker.name,
                config=worker.config,
                advanced_yaml=worker.advanced_yaml,
            )
            for worker in detail.workers
        ]

    @router.post(
        "/agent-bundles/{agent_id}/workers",
        response_model=BundleDetailResponse,
        status_code=201,
        dependencies=[Depends(require_json_content_type)],
    )
    async def create_worker(
        request: Request,
        agent_id: str,
        body: BundleWorkerCreateRequest,
    ) -> BundleDetailResponse:
        authenticate(request)
        detail = await _call(
            service.create_worker,
            agent_id,
            body.name,
            _config_dump(body.config),
            expected_version=body.expected_version,
        )
        return _detail_response(detail)

    @router.put(
        "/agent-bundles/{agent_id}/workers/order",
        response_model=BundleDetailResponse,
        dependencies=[Depends(require_json_content_type)],
    )
    async def reorder_workers(
        request: Request,
        agent_id: str,
        body: BundleWorkerOrderRequest,
    ) -> BundleDetailResponse:
        authenticate(request)
        detail = await _call(
            service.reorder_workers,
            agent_id,
            body.names,
            expected_version=body.expected_version,
        )
        return _detail_response(detail)

    @router.put(
        "/agent-bundles/{agent_id}/workers/{worker_name}",
        response_model=BundleDetailResponse,
        dependencies=[Depends(require_json_content_type)],
    )
    async def update_worker(
        request: Request,
        agent_id: str,
        worker_name: str,
        body: BundleWorkerUpdateRequest,
    ) -> BundleDetailResponse:
        authenticate(request)
        changes = _config_dump(body.changes) if body.changes is not None else {}
        detail = await _call(
            service.update_worker,
            agent_id,
            worker_name,
            changes,
            expected_version=body.expected_version,
            advanced_yaml=body.advanced_yaml,
        )
        return _detail_response(detail)

    @router.delete(
        "/agent-bundles/{agent_id}/workers/{worker_name}",
        response_model=BundleDetailResponse,
        dependencies=[Depends(require_json_content_type)],
    )
    async def delete_worker(
        request: Request,
        agent_id: str,
        worker_name: str,
        body: BundleWorkerDeleteRequest,
    ) -> BundleDetailResponse:
        authenticate(request)
        detail = await _call(
            service.delete_worker,
            agent_id,
            worker_name,
            expected_version=body.expected_version,
        )
        return _detail_response(detail)

    return router


__all__ = ["OptionsProvider", "create_agent_bundles_router"]
