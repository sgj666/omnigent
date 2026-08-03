"""Contract tests for the team-harness REST surface."""

from __future__ import annotations

import httpx
import pytest
from fastapi.responses import JSONResponse

from omnigent.errors import OmnigentError
from omnigent.server.routes.teams import TeamMemoryStore, create_teams_router
from omnigent.server.routes.workspaces import create_workspaces_router


@pytest.fixture()
async def client() -> httpx.AsyncClient:
    from fastapi import FastAPI

    app = FastAPI()

    @app.exception_handler(OmnigentError)
    async def handle_omnigent_error(_request: object, error: OmnigentError) -> JSONResponse:
        return JSONResponse(status_code=error.http_status, content={"error": error.code})

    store = TeamMemoryStore()
    app.state.team_store = store
    app.include_router(create_teams_router(store), prefix="/v1")
    app.include_router(create_workspaces_router(store), prefix="/v1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


async def test_team_crud_exposes_agent_runtime_surface(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/v1/teams",
        json={
            "name": "Delivery",
            "members": [
                {
                    "name": "Coordinator",
                    "role": "coordinator",
                    "harness": "codex",
                    "capabilities": ["plan"],
                    "concurrency": 1,
                    "pairing": {"mode": "lead"},
                    "surface": {"feishu": "active"},
                },
                {"name": "Worker", "role": "worker", "harness": "claude", "concurrency": 2},
            ],
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["coordinator"]["harness"] == "codex"
    assert body["coordinator"]["pairing"] == {"mode": "lead"}
    assert body["workers"][0]["concurrency"] == 2

    listed = await client.get("/v1/teams")
    assert listed.json()["data"] == [body]
    assert (await client.get(f"/v1/teams/{body['id']}")).json() == body


async def test_team_requires_exactly_one_coordinator(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/teams",
        json={"name": "No lead", "members": [{"name": "Worker", "role": "worker"}]},
    )
    assert response.status_code == 422


async def test_workspace_selection_copies_thread_default_and_never_rewrites_running_run(
    client: httpx.AsyncClient,
) -> None:
    first = (await client.post("/v1/workspaces", json={"root_path": "/repo/a"})).json()
    second = (await client.post("/v1/workspaces", json={"root_path": "/repo/b"})).json()
    selected = await client.post(
        f"/v1/workspaces/{first['id']}/select", json={"thread_id": "thread-1"}
    )
    assert selected.status_code == 200

    store = client._transport.app.state.team_store  # type: ignore[attr-defined]
    run = store.create_run(team_id="team", thread_id="thread-1", source="test")
    assert run["workspace_id"] == first["id"]
    run["status"] = "running"

    changed = await client.post(
        f"/v1/workspaces/{second['id']}/select",
        json={"thread_id": "thread-1", "run_id": run["id"]},
    )
    assert changed.status_code == 409
    assert run["workspace_id"] == first["id"]
