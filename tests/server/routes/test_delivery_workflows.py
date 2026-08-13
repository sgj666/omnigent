from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from omnigent.db.db_models import OmnigentBase
from omnigent.db.utils import get_or_create_engine
from omnigent.delivery_workflow import DeliveryWorkflowService
from omnigent.errors import OmnigentError
from omnigent.server.routes.delivery_workflows import create_delivery_workflows_router
from omnigent.stores.delivery_workflow_store import SqlAlchemyDeliveryWorkflowStore


class _Auth:
    @staticmethod
    def get_user_id(request: Request) -> str | None:
        return request.headers.get("x-user")


class _Runs:
    run = SimpleNamespace(
        id="1" * 32,
        actor_id="alice",
        agent_id="2" * 32,
        bundle_location=f"{'2' * 32}/{'a' * 64}",
        root_session_id="4" * 32,
    )

    def get_run(self, run_id: str) -> object | None:
        return self.run if run_id == self.run.id else None

    def get_run_by_root_session_id(self, session_id: str) -> object | None:
        return self.run if session_id == self.run.root_session_id else None


class _Cache:
    @staticmethod
    def load(_agent_id: str, _bundle_location: str) -> object:
        return SimpleNamespace(
            spec=SimpleNamespace(
                delivery_workflow=SimpleNamespace(
                    profile="zhuanspec-development",
                    role="coordinator",
                )
            )
        )


def _client(tmp_path: Path) -> tuple[TestClient, str]:
    database = f"sqlite:///{tmp_path / 'api.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    service = DeliveryWorkflowService(
        SqlAlchemyDeliveryWorkflowStore(database),
        _Runs(),  # type: ignore[arg-type]
        _Cache(),  # type: ignore[arg-type]
    )
    app = FastAPI()

    @app.exception_handler(OmnigentError)
    async def _handle(_request: Request, exc: OmnigentError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(
        create_delivery_workflows_router(service, auth_provider=_Auth()),
        prefix="/v1",
    )
    return TestClient(app), _Runs.run.id


def test_delivery_workflow_run_subresource_contract(tmp_path: Path) -> None:
    client, run_id = _client(tmp_path)
    headers = {
        "x-user": "alice",
        "x-orvia-workflow-agent-id": "2" * 32,
        "x-orvia-workflow-session-id": "4" * 32,
    }
    base = f"/v1/runs/{run_id}/delivery-workflow"

    missing = client.get(base, headers=headers)
    created = client.put(
        f"{base}/plan",
        headers=headers,
        json={
            "expected_version": 0,
            "tasks": [
                {
                    "task_key": "requirements",
                    "title": "Analyze requirements",
                    "owner_role": "requirement-analyst",
                }
            ],
        },
    )
    task_id = created.json()["planned_tasks"][0]["id"]
    evidence = client.post(
        f"{base}/artifacts",
        headers=headers,
        json={
            "kind": "intake-report",
            "location": "zhuanspec/changes/change-1/intake.md",
            "content_sha256": "b" * 64,
            "planned_task_id": task_id,
            "metadata": {"approved": True},
        },
    )
    transition_body = {
        "expected_phase": "intake",
        "expected_version": 1,
        "to_phase": "preflight",
        "to_status": "active",
        "idempotency_key": "intake-preflight",
        "evidence_refs": [evidence.json()["id"]],
    }
    transitioned = client.post(
        f"{base}/transitions",
        headers=headers,
        json=transition_body,
    )
    retry = client.post(
        f"{base}/transitions",
        headers=headers,
        json=transition_body,
    )
    hidden = client.get(base, headers=headers | {"x-user": "bob"})
    wrong_agent = client.get(
        base,
        headers=headers | {"x-orvia-workflow-agent-id": "3" * 32},
    )
    wrong_session_write = client.put(
        f"{base}/plan",
        headers=headers | {"x-orvia-workflow-session-id": "5" * 32},
        json={"expected_version": 2, "tasks": []},
    )
    wrong_agent_artifact = client.post(
        f"{base}/artifacts",
        headers=headers | {"x-orvia-workflow-agent-id": "3" * 32},
        json={
            "kind": "report",
            "location": "forged.md",
            "content_sha256": "c" * 64,
        },
    )
    wrong_session_transition = client.post(
        f"{base}/transitions",
        headers=headers | {"x-orvia-workflow-session-id": "5" * 32},
        json={
            "expected_phase": "preflight",
            "expected_version": 2,
            "to_phase": "requirement",
            "to_status": "active",
            "idempotency_key": "forged",
            "evidence_refs": [evidence.json()["id"]],
        },
    )

    assert missing.status_code == 404
    assert created.status_code == 200
    assert created.json()["run"]["phase"] == "intake"
    assert evidence.status_code == 201
    assert transitioned.status_code == retry.status_code == 200
    assert transitioned.json()["run"]["version"] == retry.json()["run"]["version"] == 2
    assert len(retry.json()["transitions"]) == 1
    assert hidden.status_code == 404
    assert wrong_agent.status_code == 404
    assert wrong_session_write.status_code == 404
    assert wrong_agent_artifact.status_code == 404
    assert wrong_session_transition.status_code == 404
    assert len(client.get(base, headers=headers).json()["transitions"]) == 1


def test_current_delivery_workflow_resolves_run_from_headers(tmp_path: Path) -> None:
    client, _run_id = _client(tmp_path)
    headers = {
        "x-user": "alice",
        "x-orvia-workflow-agent-id": "2" * 32,
        "x-orvia-workflow-session-id": "4" * 32,
    }

    created = client.put(
        "/v1/delivery-workflow/plan",
        headers=headers,
        json={"expected_version": 0, "tasks": []},
    )
    hidden = client.get(
        "/v1/delivery-workflow",
        headers=headers | {"x-orvia-workflow-session-id": "5" * 32},
    )

    assert created.status_code == 200
    assert created.json()["run"]["runtime_run_id"] == "1" * 32
    assert hidden.status_code == 404


def test_delivery_workflow_route_validation_rejects_bad_evidence_hash(tmp_path: Path) -> None:
    client, run_id = _client(tmp_path)

    response = client.post(
        f"/v1/runs/{run_id}/delivery-workflow/artifacts",
        headers={
            "x-user": "alice",
            "x-orvia-workflow-agent-id": "2" * 32,
            "x-orvia-workflow-session-id": "4" * 32,
        },
        json={
            "kind": "report",
            "location": "report.md",
            "content_sha256": "not-a-sha",
        },
    )

    assert response.status_code == 422
