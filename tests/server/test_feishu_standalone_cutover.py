"""RED contracts for removing embedded Feishu execution from Core."""

from __future__ import annotations

import importlib
import inspect
import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from omnigent.errors import OmnigentError
from omnigent.server.app import create_app

AGENT_PROXY_PATHS = {
    "/v1/agents/{agent_id}/feishu",
    "/v1/agents/{agent_id}/feishu/binding",
    "/v1/agents/{agent_id}/feishu/installations",
    "/v1/agents/{agent_id}/feishu/installations/{session}",
    "/v1/agents/{agent_id}/feishu/surface/reinitialize",
    "/v1/agents/{agent_id}/feishu/surface/status",
}

EMBEDDED_PATHS = {
    "/v1/feishu/installations",
    "/v1/feishu/installations/{session}",
    "/v1/feishu/webhook",
    "/v1/teams/{team_id}/feishu/install/begin",
    "/v1/teams/{team_id}/feishu/install/{session}/status",
    "/v1/teams/{team_id}/feishu/webhook",
}


class _HeaderAuth:
    @staticmethod
    def get_user_id(request: Request) -> str | None:
        return request.headers.get("x-user")


def _route_paths(app: FastAPI) -> set[str]:
    return {route.path for route in app.routes if hasattr(route, "path")}


def _proxy_router(
    client: httpx.AsyncClient,
    *,
    timeout_s: float = 1.0,
) -> Any:
    try:
        module = importlib.import_module("omnigent.server.routes.feishu_proxy")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Core standalone Feishu HTTP proxy is missing: {exc}")
    return module.create_feishu_proxy_router(
        integration_base_url="https://feishu-integration.test",
        integration_bearer="integration-secret",
        auth_provider=_HeaderAuth(),
        client=client,
        timeout_s=timeout_s,
    )


def test_production_app_mounts_only_agent_scoped_proxy_routes(app: FastAPI) -> None:
    paths = _route_paths(app)

    assert paths >= AGENT_PROXY_PATHS
    assert paths.isdisjoint(EMBEDDED_PATHS)
    assert not any(path.startswith("/v1/teams/") and "/feishu/" in path for path in paths)


def test_create_app_has_no_embedded_lark_adapter_parameter() -> None:
    assert "lark_adapter" not in inspect.signature(create_app).parameters


@pytest.mark.asyncio
async def test_agent_proxy_requires_core_auth_and_uses_fixed_integration_identity() -> None:
    upstream_requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        return httpx.Response(201, json={"object": "feishu.installation", "id": "install-1"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(upstream),
        base_url="https://feishu-integration.test",
    ) as upstream_client:
        proxy = FastAPI()

        @proxy.exception_handler(OmnigentError)
        async def handle_error(_request: Request, error: OmnigentError) -> JSONResponse:
            return JSONResponse(
                status_code=error.http_status,
                content={"error": {"code": error.code, "message": error.message}},
            )

        proxy.include_router(_proxy_router(upstream_client), prefix="/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://core.test"
        ) as client:
            unauthorized = await client.post(
                "/v1/agents/agent-1/feishu/installations",
                headers={"authorization": "Bearer user-secret"},
            )
            authorized = await client.post(
                "/v1/agents/agent-1/feishu/installations?locale=zh-CN",
                headers={
                    "x-user": "alice",
                    "authorization": "Bearer user-secret",
                    "cookie": "core_session=user-cookie",
                },
                json={"workspace_id": "workspace-1"},
            )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 201
    assert authorized.json() == {"object": "feishu.installation", "id": "install-1"}
    assert len(upstream_requests) == 1
    forwarded = upstream_requests[0]
    assert forwarded.url.path == "/v1/agents/agent-1/feishu/installations"
    assert forwarded.url.query == b"locale=zh-CN"
    assert json.loads(forwarded.content) == {"workspace_id": "workspace-1"}
    assert forwarded.headers["content-type"].startswith("application/json")
    assert forwarded.headers["authorization"] == "Bearer integration-secret"
    assert forwarded.headers["x-omnigent-user"] == "alice"
    assert "cookie" not in forwarded.headers
    assert "user-secret" not in str(forwarded.headers)


@pytest.mark.asyncio
async def test_agent_proxy_preserves_safe_upstream_authorization_errors() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": {"code": "installation_forbidden"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(upstream),
        base_url="https://feishu-integration.test",
    ) as upstream_client:
        proxy = FastAPI()
        proxy.include_router(_proxy_router(upstream_client), prefix="/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://core.test"
        ) as client:
            response = await client.get(
                "/v1/agents/agent-1/feishu",
                headers={"x-user": "alice"},
            )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "installation_forbidden"}}


@pytest.mark.asyncio
async def test_agent_proxy_maps_transport_failures_without_touching_run_runtime() -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("standalone unavailable")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(upstream),
        base_url="https://feishu-integration.test",
    ) as upstream_client:
        proxy = FastAPI()
        proxy.include_router(_proxy_router(upstream_client, timeout_s=0.01), prefix="/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://core.test"
        ) as client:
            response = await client.post(
                "/v1/agents/agent-1/feishu/surface/reinitialize",
                headers={"x-user": "alice"},
            )

    assert response.status_code == 504
    assert response.json() == {
        "detail": {
            "code": "feishu_integration_timeout",
            "message": "Standalone Feishu integration timed out",
        }
    }

    module = importlib.import_module("omnigent.server.routes.feishu_proxy")
    unconfigured = FastAPI()
    unconfigured.include_router(
        module.create_feishu_proxy_router(
            integration_base_url=None,
            integration_bearer=None,
            auth_provider=_HeaderAuth(),
        ),
        prefix="/v1",
    )

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("standalone unavailable", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unavailable),
        base_url="https://feishu-integration.test",
    ) as upstream_client:
        unavailable_app = FastAPI()
        unavailable_app.include_router(_proxy_router(upstream_client), prefix="/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=unavailable_app),
            base_url="http://core.test",
        ) as client:
            unavailable_response = await client.get(
                "/v1/agents/agent-1/feishu",
                headers={"x-user": "alice"},
            )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=unconfigured),
        base_url="http://core.test",
    ) as client:
        unconfigured_response = await client.get(
            "/v1/agents/agent-1/feishu",
            headers={"x-user": "alice"},
        )

    for unavailable_result in (unavailable_response, unconfigured_response):
        assert unavailable_result.status_code == 503
        assert unavailable_result.json() == {
            "detail": {
                "code": "feishu_integration_unavailable",
                "message": "Standalone Feishu integration is unavailable",
            }
        }


def test_proxy_router_has_an_explicit_path_allowlist_only() -> None:
    async def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream),
        base_url="https://feishu-integration.test",
    )
    try:
        router = _proxy_router(upstream_client)
        paths = {route.path for route in router.routes}
    finally:
        import asyncio

        asyncio.run(upstream_client.aclose())

    assert paths == {path.removeprefix("/v1") for path in AGENT_PROXY_PATHS}
    assert not any("{path:path}" in path or "{proxy_path" in path for path in paths)
