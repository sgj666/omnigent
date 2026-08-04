from __future__ import annotations

import importlib
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from omnigent.errors import OmnigentError


def _modules() -> tuple[Any, Any]:
    try:
        entities = importlib.import_module("omnigent.entities.run_evaluation")
        routes = importlib.import_module("omnigent.server.routes.run_evaluations")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Run evaluation API is missing: {exc}")
    return entities, routes


class _BearerAuth:
    @staticmethod
    def get_user_id(request: Request) -> str | None:
        return request.headers.get("authorization", "").removeprefix("Bearer ") or None


def _record(entities: Any, status: Any) -> Any:
    return entities.EvaluationRecord(
        id="a" * 32,
        run_id="1" * 32,
        owner_user_id="alice",
        evaluator="session-collaboration",
        version=1,
        status=status,
        metrics=entities.EvaluationMetrics(
            task_completion_rate=0.5,
            attempt_success_rate=0.5,
            retry_count=1,
            blocked_count=0,
            blocked_duration_seconds=0,
            parallel_overlap_seconds=5,
            max_concurrency=2,
            worker_duration_seconds=20,
            parent_inbox_latency_seconds=None,
            parent_inbox_latency_samples=0,
            failure_categories={},
            evidence_counts=entities.EvidenceCounts(),
        ),
        workers=(),
        evidence_refs=(),
        rubric=None,
        created_at=10,
        updated_at=10,
    )


def _app() -> tuple[FastAPI, Any]:
    entities, routes = _modules()

    class Service:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bool, str]] = []

        def get_or_evaluate(self, run_id: str, *, owner_user_id: str) -> Any:
            self.calls.append((run_id, owner_user_id, False, "get"))
            status = (
                entities.EvaluationStatus.PREVIEW
                if run_id == "2" * 32
                else entities.EvaluationStatus.FINAL
            )
            return _record(entities, status)

        def evaluate(self, run_id: str, *, owner_user_id: str, refresh: bool = False) -> Any:
            self.calls.append((run_id, owner_user_id, refresh, "post"))
            return _record(entities, entities.EvaluationStatus.FINAL)

    service = Service()
    app = FastAPI()

    @app.exception_handler(OmnigentError)
    async def handle_error(_request: Request, error: OmnigentError) -> JSONResponse:
        return JSONResponse(
            status_code=error.http_status,
            content={"error": {"code": error.code, "message": error.message}},
        )

    app.include_router(
        routes.create_run_evaluations_router(
            service,
            auth_provider=_BearerAuth(),
            owner_check=lambda run_id, actor: run_id != "f" * 32 and actor == "alice",
        ),
        prefix="/v1",
    )
    return app, service


@pytest.mark.asyncio
async def test_api_auth_preview_final_refresh_and_owner_isolation() -> None:
    app, service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://core"
    ) as client:
        unauthenticated = await client.get(f"/v1/runs/{'1' * 32}/evaluation")
        preview = await client.get(
            f"/v1/runs/{'2' * 32}/evaluation",
            headers={"Authorization": "Bearer alice"},
        )
        final = await client.get(
            f"/v1/runs/{'1' * 32}/evaluation",
            headers={"Authorization": "Bearer alice"},
        )
        refreshed = await client.post(
            f"/v1/runs/{'1' * 32}/evaluation",
            headers={"Authorization": "Bearer alice"},
            json={"refresh": True},
        )
        hidden = await client.get(
            f"/v1/runs/{'f' * 32}/evaluation",
            headers={"Authorization": "Bearer alice"},
        )

    assert unauthenticated.status_code == 401
    assert preview.status_code == 200 and preview.json()["status"] == "preview"
    assert final.status_code == 200 and final.json()["status"] == "final"
    assert refreshed.status_code == 200
    assert ("1" * 32, "alice", True, "post") in service.calls
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_api_rejects_unknown_body_fields() -> None:
    app, _service = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://core"
    ) as client:
        response = await client.post(
            f"/v1/runs/{'1' * 32}/evaluation",
            headers={"Authorization": "Bearer alice"},
            json={"refresh": True, "prompt": "do not persist me"},
        )

    assert response.status_code == 422
