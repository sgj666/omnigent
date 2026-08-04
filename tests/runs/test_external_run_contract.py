"""RED contract for authenticated, provider-neutral external Run control."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from pydantic import ValidationError

from omnigent.db.db_models import OmnigentBase
from omnigent.db.utils import get_or_create_engine
from omnigent.entities import Agent
from omnigent.entities.run_projection import RunCreate, RunStatus
from omnigent.runs.service import RunService
from omnigent.server.routes.runs import create_runs_router
from omnigent.server.schemas import CreateRunRequest
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore

_SOURCE_PATTERN = r"^[a-z][a-z0-9_-]*(?::[a-z0-9_-]+)?$"


def _external_payload(**changes: object) -> dict[str, object]:
    return {
        "agent_id": "1" * 32,
        "workspace_id": "workspace-1",
        "input": "implement auth and review it",
        "source": "integration:feishu",
        "source_event_id": "feishu:event-1",
        "host_id": None,
        "execution_mode": "auto",
    } | changes


def test_create_run_schema_accepts_exact_external_command() -> None:
    request = CreateRunRequest.model_validate(_external_payload())

    assert request.model_dump() == _external_payload()


@pytest.mark.parametrize("workspace", [None, pytest.param("omitted", id="omitted")])
def test_create_run_schema_allows_optional_workspace(workspace: str | None) -> None:
    payload = _external_payload(workspace_id=workspace)
    if workspace == "omitted":
        payload.pop("workspace_id")

    request = CreateRunRequest.model_validate(payload)

    assert request.workspace_id is None


def test_create_run_source_pattern_is_provider_neutral_and_namespaced() -> None:
    schema = CreateRunRequest.model_json_schema()

    assert schema["properties"]["source"]["pattern"] == _SOURCE_PATTERN
    assert CreateRunRequest.model_validate(_external_payload(source="api")).source == "api"
    assert (
        CreateRunRequest.model_validate(_external_payload(source="integration:feishu")).source
        == "integration:feishu"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_actor", "ou_forged"),
        ("team_id", "team-forged"),
        ("profile_id", "profile-forged"),
        ("prompt", "legacy prompt"),
        ("provider", "feishu"),
    ],
)
def test_create_run_schema_rejects_identity_legacy_and_provider_extras(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        CreateRunRequest.model_validate(_external_payload(**{field: value}))

    assert any(
        error["loc"] == (field,) and error["type"] == "extra_forbidden"
        for error in raised.value.errors()
    )


@pytest.mark.parametrize("source", ["Integration:feishu", "integration:fei:shu", "a.b"])
def test_create_run_schema_rejects_sources_outside_exact_pattern(source: str) -> None:
    with pytest.raises(ValidationError) as raised:
        CreateRunRequest.model_validate(_external_payload(source=source))

    assert any(error["loc"] == ("source",) for error in raised.value.errors())


class _BearerAuth:
    @staticmethod
    def get_user_id(request: Request) -> str | None:
        authorization = request.headers.get("authorization", "")
        return authorization.removeprefix("Bearer ") or None


def _run_api(tmp_path: Path, *, failing_root: bool = False) -> tuple[FastAPI, SqlAlchemyRunStore]:
    database = f"sqlite:///{tmp_path / 'external-contract.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    store = SqlAlchemyRunStore(database)
    root = tmp_path / "workspace"
    (root / "repo" / ".git").mkdir(parents=True)
    workspace = store.create_workspace(root_path=str(root), repositories=(("repo", "repo"),))
    agent = Agent(
        id="1" * 32,
        created_at=1,
        name="coordinator",
        version=1,
        bundle_location=f"{'1' * 32}/{'2' * 64}",
    )

    class Agents:
        @staticmethod
        def get(agent_id: str) -> Agent | None:
            return agent if agent_id == agent.id else None

    if failing_root:

        class Conversations:
            @staticmethod
            def create_conversation(**_kwargs: Any) -> None:
                raise RuntimeError("root Session allocation failed")

        conversations: Any = Conversations()
    else:
        conversations = SqlAlchemyConversationStore(database)

    async def submit(_session_id: str, _event: object, _actor_id: str) -> None:
        return None

    service = RunService(
        run_store=store,
        conversation_store=conversations,
        agent_store=Agents(),
        submit_session_event=submit,
    )
    app = FastAPI()
    app.include_router(
        create_runs_router(store, service, auth_provider=_BearerAuth()), prefix="/v1"
    )
    app.state.contract_workspace_id = workspace.id
    app.state.contract_agent = agent
    app.state.contract_service = service
    return app, store


@pytest.mark.asyncio
async def test_external_event_is_idempotent_and_actor_comes_only_from_bearer(
    tmp_path: Path,
) -> None:
    app, _store = _run_api(tmp_path)
    payload = _external_payload(workspace_id=app.state.contract_workspace_id)
    headers = {"Authorization": "Bearer alice"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://core"
    ) as client:
        first = await client.post("/v1/runs", json=payload, headers=headers)
        second = await client.post("/v1/runs", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["actor_id"] == "alice"


def test_run_detail_and_inspector_alias_use_one_explicit_response_dto(tmp_path: Path) -> None:
    app, _store = _run_api(tmp_path)
    routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1/runs/{run_id}")
    }

    detail_model = routes["/v1/runs/{run_id}"].response_model
    inspector_model = routes["/v1/runs/{run_id}/inspector"].response_model
    assert detail_model is not None
    assert inspector_model is detail_model
    assert detail_model.model_config["extra"] == "forbid"


def test_stop_and_necessary_approval_routes_are_explicit_capabilities(tmp_path: Path) -> None:
    app, _store = _run_api(tmp_path)
    route_keys = {
        (route.path, method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or ())
    }

    assert ("/v1/runs/{run_id}/stop", "POST") in route_keys
    assert (
        "/v1/runs/{run_id}/approvals/{approval_id}/{decision}",
        "POST",
    ) in route_keys


@pytest.mark.asyncio
async def test_root_session_failure_does_not_leave_an_accepted_run(tmp_path: Path) -> None:
    app, store = _run_api(tmp_path, failing_root=True)
    fields = RunCreate.__dataclass_fields__
    command: dict[str, object] = {
        "agent_id": app.state.contract_agent.id,
        "workspace_id": app.state.contract_workspace_id,
        "source": "integration:feishu" if "input" in fields else "integration-feishu",
        "source_event_id": "feishu:root-failure",
    }
    command["input" if "input" in fields else "prompt"] = "create the root"
    if "host_id" in fields:
        command["host_id"] = None
    if "execution_mode" in fields:
        command["execution_mode"] = "auto"

    with pytest.raises(RuntimeError, match="root Session allocation failed"):
        await app.state.contract_service.create(
            RunCreate(**command),
            actor_id="alice",
            auth_scope="user:alice",
        )

    failed = store.list_runs(actor_id="alice")
    assert len(failed) == 1
    assert failed[0].status is RunStatus.FAILED
    assert failed[0].root_session_id is None
    failure_events = store.list_projection_events(failed[0].id)
    assert [(event.event_type, event.payload["failure_code"]) for event in failure_events] == [
        ("run.creation.failed", "internal_error")
    ]
