"""RED cross-process contract between CoreClient and the real Core Run router."""

from __future__ import annotations

from dataclasses import asdict

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from omnigent_feishu.auth import StaticBearerProvider
from omnigent_feishu.core_client import CoreClient, RunCreateCommand

from omnigent.entities.run_projection import (
    CreateRunResult,
    InspectorRun,
    Run,
    RunStatus,
)
from omnigent.runtime import pending_elicitations
from omnigent.server.routes.runs import create_runs_router


class _BearerAuth:
    @staticmethod
    def get_user_id(request: Request) -> str | None:
        return request.headers.get("authorization", "").removeprefix("Bearer ") or None


class _CoreStore:
    def __init__(self) -> None:
        self.run: Run | None = None

    def get_run(self, run_id: str) -> Run | None:
        return self.run if self.run is not None and self.run.id == run_id else None

    def list_runs(self, *, actor_id: str | None = None) -> tuple[Run, ...]:
        return (self.run,) if self.run is not None and self.run.actor_id == actor_id else ()

    def list_projection_events(self, _run_id: str) -> tuple[object, ...]:
        return ()

    def inspect_run(self, run_id: str) -> InspectorRun:
        assert self.run is not None and self.run.id == run_id
        return InspectorRun(
            run=self.run,
            root_session_id=self.run.root_session_id,
            child_session_ids=(),
            conversation_item_ids=(),
            tasks=(),
            attempts=(),
            failures=(),
        )


class _CoreService:
    def __init__(self, store: _CoreStore) -> None:
        self.store = store
        self.command = None

    async def create(
        self,
        command,
        *,
        actor_id: str,
        auth_scope: str,
        **_kwargs,
    ) -> CreateRunResult:
        self.command = command
        run = Run(
            id="run-1",
            actor_id=actor_id,
            auth_scope=auth_scope,
            source=command.source,
            source_event_id=command.source_event_id,
            agent_id=command.agent_id,
            bundle_version=1,
            bundle_digest="2" * 64,
            bundle_location=f"{command.agent_id}/{'2' * 64}",
            workspace_id=command.workspace_id,
            root_session_id="session-root",
            status=RunStatus.RUNNING,
            created_at=1,
        )
        self.store.run = run
        return CreateRunResult(run, True)


class _CoreGateway:
    async def create_root(self, *_args, **_kwargs) -> str:
        return "session-root"

    async def send_input(self, *_args, **_kwargs) -> None:
        return None

    async def stop(self, _session_id: str) -> None:
        return None

    async def decide_approval(
        self,
        _session_id: str,
        _approval_id: str,
        _decision: str,
    ) -> None:
        return None


def _real_core_app() -> tuple[FastAPI, _CoreStore]:
    store = _CoreStore()
    app = FastAPI()
    app.include_router(
        create_runs_router(store, _CoreService(store), auth_provider=_BearerAuth()),  # type: ignore[arg-type]
        prefix="/v1",
    )
    return app, store


@pytest.mark.asyncio
async def test_feishu_exact_create_payload_passes_real_core_schema_and_router() -> None:
    app, store = _real_core_app()
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://core")
    client = CoreClient("http://core", StaticBearerProvider("alice"), client=http)

    created = await client.create_run(
        RunCreateCommand(
            agent_id="1" * 32,
            workspace_id="workspace-1",
            input="implement auth",
            source_event_id="feishu:event-1",
            host_id="host-1",
            execution_mode="auto",
        )
    )

    assert created["id"] == "run-1"
    assert store.run is not None and store.run.actor_id == "alice"
    await http.aclose()


@pytest.mark.asyncio
async def test_feishu_detail_and_inspector_resolve_to_same_explicit_dto() -> None:
    app, store = _real_core_app()
    service = _CoreService(store)
    await service.create(
        type(
            "Command",
            (),
            {
                "source": "integration:feishu",
                "source_event_id": "feishu:event",
                "agent_id": "1" * 32,
                "workspace_id": "workspace-1",
            },
        )(),
        actor_id="alice",
        auth_scope="user:alice",
    )
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://core")
    client = CoreClient("http://core", StaticBearerProvider("alice"), client=http)

    detail = await client.get_run("run-1")
    inspector = await client.get_run_inspector("run-1")

    assert detail == inspector
    assert detail == jsonable_encoder(
        asdict(store.inspect_run("run-1")) | {"object": "run.inspector"}
    )
    await http.aclose()


@pytest.mark.asyncio
async def test_feishu_stop_and_approval_calls_are_real_core_capabilities() -> None:
    store = _CoreStore()
    service = _CoreService(store)
    await service.create(
        type(
            "Command",
            (),
            {
                "source": "integration:feishu",
                "source_event_id": "feishu:event",
                "agent_id": "1" * 32,
                "workspace_id": "workspace-1",
            },
        )(),
        actor_id="alice",
        auth_scope="user:alice",
    )
    gateway = _CoreGateway()
    app = FastAPI()
    app.include_router(
        create_runs_router(
            store,  # type: ignore[arg-type]
            service,  # type: ignore[arg-type]
            auth_provider=_BearerAuth(),
            session_gateway_factory=lambda _request: gateway,  # type: ignore[arg-type]
        ),
        prefix="/v1",
    )
    for approval_id in ("approval-1", "approval-2"):
        pending_elicitations.record_publish(
            "session-root",
            {
                "type": "response.elicitation_request",
                "elicitation_id": approval_id,
            },
        )
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://core")
    client = CoreClient("http://core", StaticBearerProvider("alice"), client=http)

    stopped = await client.stop_run("run-1")
    approved = await client.decide_approval("run-1", "approval-1", approved=True)
    denied = await client.decide_approval("run-1", "approval-2", approved=False)

    assert stopped["status"] in {"cancelled", "stopping"}
    assert approved["decision"] == "approve"
    assert denied["decision"] == "deny"
    pending_elicitations.resolve("session-root", "approval-1")
    pending_elicitations.resolve("session-root", "approval-2")
    await http.aclose()
