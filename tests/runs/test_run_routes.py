from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from omnigent.db.db_models import OmnigentBase
from omnigent.db.utils import get_or_create_engine
from omnigent.entities import Agent
from omnigent.errors import OmnigentError
from omnigent.runs.service import RunService
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.routes.runs import create_runs_router
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore


class _HeaderAuth:
    @staticmethod
    def get_user_id(request: Request) -> str | None:
        return request.headers.get("x-user")


@pytest.mark.asyncio
async def test_runs_api_is_authenticated_idempotent_and_rejects_execution_fields(
    tmp_path: Path,
) -> None:
    database = f"sqlite:///{tmp_path / 'api.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    store = SqlAlchemyRunStore(database)
    conversations = SqlAlchemyConversationStore(database)
    root = tmp_path / "workspace"
    (root / "api" / ".git").mkdir(parents=True)
    workspace = store.create_workspace(root_path=str(root), repositories=(("api", "api"),))
    digest = "2" * 64
    agent = Agent(
        id="1" * 32,
        created_at=1,
        name="coordinator",
        version=3,
        bundle_location=f"{'1' * 32}/{digest}",
    )

    class _Agents:
        @staticmethod
        def get(agent_id: str) -> Agent | None:
            return agent if agent_id == agent.id else None

    submitted: list[str] = []

    async def submit(session_id: str, event: object, actor_id: str) -> None:
        submitted.append(session_id)

    service = RunService(
        run_store=store,
        conversation_store=conversations,
        agent_store=_Agents(),
        submit_session_event=submit,
    )
    app = FastAPI()

    @app.exception_handler(OmnigentError)
    async def _handle(_request: Request, exc: OmnigentError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(
        create_runs_router(store, service, auth_provider=_HeaderAuth()),
        prefix="/v1",
    )
    payload = {
        "agent_id": agent.id,
        "workspace_id": workspace.id,
        "source": "api.request-v1",
        "source_event_id": "request-1",
        "prompt": "Coordinate this change",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        unauthorized = await client.post("/v1/runs", json=payload)
        first = await client.post("/v1/runs", json=payload, headers={"x-user": "alice"})
        second = await client.post("/v1/runs", json=payload, headers={"x-user": "alice"})
        listing = await client.get("/v1/runs", headers={"x-user": "alice"})
        detail = await client.get(f"/v1/runs/{first.json()['id']}", headers={"x-user": "alice"})
        events = await client.get(
            f"/v1/runs/{first.json()['id']}/events", headers={"x-user": "alice"}
        )
        inspector = await client.get(
            f"/v1/runs/{first.json()['id']}/inspector", headers={"x-user": "alice"}
        )
        hidden = await client.get(f"/v1/runs/{first.json()['id']}", headers={"x-user": "bob"})
        forbidden_fields = []
        for field in ("source_actor", "team_id", "profile_id", "provider"):
            forbidden_fields.append(
                await client.post(
                    "/v1/runs",
                    json=payload | {field: "forged"},
                    headers={"x-user": "alice"},
                )
            )

    assert unauthorized.status_code == 401
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["actor_id"] == "alice"
    assert listing.status_code == detail.status_code == events.status_code == 200
    assert listing.json()["data"] == [detail.json()]
    assert [event["event_type"] for event in events.json()["data"]] == ["run.root.created"]
    assert inspector.status_code == 200
    assert inspector.json()["root_session_id"] == first.json()["root_session_id"]
    assert inspector.json()["child_session_ids"] == []
    assert hidden.status_code == 404
    assert [response.status_code for response in forbidden_fields] == [422, 422, 422, 422]
    assert len(submitted) == 1


def test_app_mounts_runs_and_agent_bundle_composition_roots(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'app.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    agents = SqlAlchemyAgentStore(database)
    app = create_app(
        agent_store=agents,
        file_store=SqlAlchemyFileStore(database),
        conversation_store=SqlAlchemyConversationStore(database),
        artifact_store=artifacts,
        agent_cache=AgentCache(artifact_store=artifacts, cache_dir=tmp_path / "cache"),
        server_config={"allowed_workspace_roots": [str(tmp_path)]},
    )

    route_keys = {
        (route.path, method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or ())
    }
    assert ("/v1/runs", "POST") in route_keys
    assert ("/v1/runs/{run_id}/inspector", "GET") in route_keys
    assert ("/v1/agent-bundles", "GET") in route_keys
    assert app.state.run_store is not None
    assert app.state.run_service is not None
