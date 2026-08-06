"""Restricted Core HTTP proxy for the standalone Feishu integration."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from omnigent.server.auth import RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import require_user

_TIMEOUT_DETAIL = {
    "code": "feishu_integration_timeout",
    "message": "Standalone Feishu integration timed out",
}
_UNAVAILABLE_DETAIL = {
    "code": "feishu_integration_unavailable",
    "message": "Standalone Feishu integration is unavailable",
}


def create_feishu_proxy_router(
    *,
    integration_base_url: str | None,
    integration_bearer: str | None,
    auth_provider: AuthProvider | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 10.0,
) -> APIRouter:
    """Expose only the Agent-scoped standalone Feishu control surface."""
    router = APIRouter()

    async def forward(request: Request, upstream_path: str) -> Response:
        actor_id = require_user(request, auth_provider) or RESERVED_USER_LOCAL
        if not integration_base_url or not integration_bearer:
            raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)

        headers = {
            "authorization": f"Bearer {integration_bearer}",
            "x-omnigent-user": actor_id,
        }
        content_type = request.headers.get("content-type")
        if content_type:
            headers["content-type"] = content_type
        request_body = await request.body()
        request_url = f"{integration_base_url.rstrip('/')}{upstream_path}"
        request_kwargs: dict[str, Any] = {
            "method": request.method,
            "url": request_url,
            "params": list(request.query_params.multi_items()),
            "content": request_body,
            "headers": headers,
            "timeout": timeout_s,
        }
        try:
            if client is not None:
                upstream = await client.request(**request_kwargs)
            else:
                async with httpx.AsyncClient() as integration_client:
                    upstream = await integration_client.request(**request_kwargs)
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail=_TIMEOUT_DETAIL) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from exc

        if 400 <= upstream.status_code < 500:
            return _safe_client_error(upstream)
        if upstream.status_code >= 500:
            raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)
        response_headers = {}
        if upstream_content_type := upstream.headers.get("content-type"):
            response_headers["content-type"] = upstream_content_type
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    @router.post("/agents/{agent_id}/feishu/installations")
    async def begin_installation(request: Request, agent_id: str) -> Response:
        return await forward(request, f"/v1/agents/{agent_id}/feishu/installations")

    @router.get("/agents/{agent_id}/feishu/installations/{session}")
    async def poll_installation(request: Request, agent_id: str, session: str) -> Response:
        return await forward(
            request,
            f"/v1/agents/{agent_id}/feishu/installations/{session}",
        )

    @router.get("/agents/{agent_id}/feishu")
    async def installation_status(request: Request, agent_id: str) -> Response:
        return await forward(request, f"/v1/agents/{agent_id}/feishu")

    @router.delete("/agents/{agent_id}/feishu")
    async def delete_installation(request: Request, agent_id: str) -> Response:
        return await forward(request, f"/v1/agents/{agent_id}/feishu")

    @router.put("/agents/{agent_id}/feishu/binding")
    async def update_binding(request: Request, agent_id: str) -> Response:
        return await forward(request, f"/v1/agents/{agent_id}/feishu/binding")

    @router.put("/agents/{agent_id}/feishu/workspace-scope")
    async def update_workspace_scope(request: Request, agent_id: str) -> Response:
        return await forward(request, f"/v1/agents/{agent_id}/feishu/workspace-scope")

    @router.get("/agents/{agent_id}/feishu/default-workspace")
    @router.put("/agents/{agent_id}/feishu/default-workspace")
    async def default_workspace_scope(request: Request, agent_id: str) -> Response:
        return await forward(request, f"/v1/agents/{agent_id}/feishu/default-workspace")

    @router.get("/agents/{agent_id}/feishu/surface/status")
    async def surface_status(request: Request, agent_id: str) -> Response:
        return await forward(request, f"/v1/agents/{agent_id}/feishu/surface/status")

    @router.post("/agents/{agent_id}/feishu/surface/reinitialize")
    async def reinitialize_surface(request: Request, agent_id: str) -> Response:
        return await forward(
            request,
            f"/v1/agents/{agent_id}/feishu/surface/reinitialize",
        )

    return router


def _safe_client_error(upstream: httpx.Response) -> JSONResponse:
    try:
        payload = upstream.json()
    except ValueError:
        payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, (dict, list, str, int, float, bool)) and detail is not None:
        detail = None
    if detail is None:
        detail = {
            "code": "feishu_integration_rejected",
            "message": "Standalone Feishu integration rejected the request",
        }
    return JSONResponse(status_code=upstream.status_code, content={"detail": detail})
