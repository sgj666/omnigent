"""Cutover contracts for the retired embedded Feishu router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omnigent.server.routes.feishu import create_feishu_router


def test_legacy_embedded_routes_are_provider_neutral_and_gone() -> None:
    app = FastAPI()
    app.include_router(create_feishu_router())
    client = TestClient(app)

    responses = (
        client.post("/feishu/installations"),
        client.get("/feishu/installations/session-1"),
        client.post("/teams/team-1/feishu/install/begin"),
        client.get("/teams/team-1/feishu/install/session-1/status"),
        client.post("/teams/team-1/feishu/webhook"),
        client.post("/feishu/webhook"),
    )

    assert {response.status_code for response in responses} == {410}
    assert all(
        response.json()["detail"]["code"] == "embedded_feishu_retired" for response in responses
    )


def test_legacy_router_is_not_mounted_by_production_app(app: FastAPI) -> None:
    paths = {route.path for route in app.routes}

    assert "/v1/feishu/installations" not in paths
    assert "/v1/feishu/webhook" not in paths
    assert not any(path.startswith("/v1/teams/") and "/feishu/" in path for path in paths)
