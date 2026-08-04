"""Contract tests for the team-harness REST surface."""

from __future__ import annotations

import httpx
import pytest
from fastapi.responses import JSONResponse

from omnigent.errors import OmnigentError
from omnigent.server.routes.teams import (
    SqlAlchemyTeamWorkspaceStore,
    TeamMemoryStore,
    create_teams_router,
)
from omnigent.server.routes.workspaces import create_workspaces_router
from omnigent.server.schemas import CreateTeamRequest


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


async def test_legacy_team_reads_remain_diagnostic_and_writes_are_gone(
    client: httpx.AsyncClient,
) -> None:
    store = client._transport.app.state.team_store  # type: ignore[attr-defined]
    body = store.create_team(
        CreateTeamRequest(
            name="Delivery",
            members=[
                {"name": "Coordinator", "role": "coordinator"},
                {"name": "Worker", "role": "worker"},
            ],
        )
    )

    listed = await client.get("/v1/teams")
    assert listed.json()["data"] == [body]
    assert (await client.get(f"/v1/teams/{body['id']}")).json() == body

    write_requests = (
        ("POST", "/v1/teams", {"name": "New", "members": []}),
        ("PATCH", f"/v1/teams/{body['id']}", {"name": "Changed"}),
        ("DELETE", f"/v1/teams/{body['id']}", None),
        ("POST", f"/v1/teams/{body['id']}/start", None),
        ("POST", "/v1/runs/legacy/retry", None),
        ("POST", "/v1/runs/legacy/approve", None),
        ("POST", "/v1/runs/legacy/assign", None),
    )
    for method, path, payload in write_requests:
        response = await client.request(method, path, json=payload)
        assert response.status_code == 410, (method, path, response.text)


async def test_team_requires_exactly_one_coordinator(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/teams",
        json={"name": "No lead", "members": [{"name": "Worker", "role": "worker"}]},
    )
    assert response.status_code == 410


async def test_run_inspector_endpoint_returns_run_or_not_found(
    client: httpx.AsyncClient,
) -> None:
    store = client._transport.app.state.team_store  # type: ignore[attr-defined]
    run = store.create_run(team_id="team", thread_id="thread", source="test")

    response = await client.get(f"/v1/runs/{run['id']}")
    assert response.status_code == 200
    assert response.json() == run
    assert (await client.get("/v1/runs/missing")).status_code == 404


async def test_workspace_selection_copies_thread_default_and_never_rewrites_running_run(
    client: httpx.AsyncClient,
    tmp_path: object,
) -> None:
    from pathlib import Path

    first_root = Path(str(tmp_path)) / "a"
    second_root = Path(str(tmp_path)) / "b"
    first_root.mkdir()
    second_root.mkdir()
    first = (await client.post("/v1/workspaces", json={"root_path": str(first_root)})).json()
    second = (await client.post("/v1/workspaces", json={"root_path": str(second_root)})).json()
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


def test_sql_store_restores_workspace_selection_after_restart(tmp_path: object) -> None:
    """A new store instance reads the durable default selected by its predecessor."""
    from pathlib import Path

    from omnigent.db.db_models import OmnigentBase
    from omnigent.db.utils import get_or_create_engine

    database = f"sqlite:///{Path(str(tmp_path)) / 'teams.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    first = SqlAlchemyTeamWorkspaceStore(database)
    workspace = {"id": "1" * 32, "root_path": "/repo", "repositories": []}
    first.workspaces[workspace["id"]] = {"object": "workspace", **workspace}
    first.persist_workspace(workspace)
    first.select_thread_workspace("thread-1", workspace["id"])

    restored = SqlAlchemyTeamWorkspaceStore(database)
    assert restored.thread_workspaces == {"thread-1": workspace["id"]}
    assert restored.workspaces[workspace["id"]]["root_path"] == "/repo"


async def test_queued_run_workspace_switch_survives_store_restart(tmp_path: object) -> None:
    """Selecting B for a queued run updates both SQL and the live cache."""
    from pathlib import Path

    from fastapi import FastAPI

    from omnigent.db.db_models import OmnigentBase
    from omnigent.db.utils import get_or_create_engine

    database = f"sqlite:///{Path(str(tmp_path)) / 'queued-run.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    store = SqlAlchemyTeamWorkspaceStore(database)
    app = FastAPI()
    app.include_router(create_workspaces_router(store), prefix="/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as sql_client:
        first_root = Path(str(tmp_path)) / "a"
        second_root = Path(str(tmp_path)) / "b"
        first_root.mkdir()
        second_root.mkdir()
        first = (
            await sql_client.post("/v1/workspaces", json={"root_path": str(first_root)})
        ).json()
        second = (
            await sql_client.post("/v1/workspaces", json={"root_path": str(second_root)})
        ).json()
        await sql_client.post(f"/v1/workspaces/{first['id']}/select", json={"thread_id": "thread"})
        run = store.create_run(team_id="2" * 32, thread_id="thread", source="test")
        response = await sql_client.post(
            f"/v1/workspaces/{second['id']}/select",
            json={"thread_id": "thread", "run_id": run["id"]},
        )

    assert response.status_code == 200
    assert store.runs[run["id"]]["workspace_id"] == second["id"]
    restored = SqlAlchemyTeamWorkspaceStore(database)
    assert restored.runs[run["id"]]["workspace_id"] == second["id"]


async def test_invalid_repository_is_rejected_without_partial_workspace(
    client: httpx.AsyncClient,
) -> None:
    """Repository validation happens before a workspace reaches the store."""
    response = await client.post(
        "/v1/workspaces", json={"root_path": "/repo", "repositories": [{}]}
    )
    assert response.status_code == 422
    assert (await client.get("/v1/workspaces")).json()["data"] == []


@pytest.mark.parametrize(
    "repositories",
    [
        [{"name": "repo", "path": "/a"}, {"name": "repo", "path": "/b"}],
        [{"name": "a", "path": "/repo"}, {"name": "b", "path": "/repo"}],
    ],
)
async def test_duplicate_repositories_are_rejected_before_workspace_write(
    client: httpx.AsyncClient, repositories: list[dict[str, str]]
) -> None:
    """Duplicate repository names or paths cannot partially create a workspace."""
    response = await client.post(
        "/v1/workspaces", json={"root_path": "/repo", "repositories": repositories}
    )
    assert response.status_code == 422
    assert (await client.get("/v1/workspaces")).json()["data"] == []
