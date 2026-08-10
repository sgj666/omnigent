"""Provider-neutral Agent Bundle router contract tests."""

from __future__ import annotations

import base64
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omnigent.agent_bundles.service import (
    BundleCard,
    BundleDetail,
    BundleIssue,
    BundlePage,
    BundleValidationFailure,
    BundleValidationResult,
)
from omnigent.agent_bundles.workers import BundleAgentView
from omnigent.server.routes.agent_bundles import create_agent_bundles_router
from omnigent.skills.reader import (
    SkillRecord,
    SkillRepositorySource,
    SkillSnapshot,
)
from omnigent.stores.agent_store import AgentVersionConflict


def _detail(version: int = 1) -> BundleDetail:
    card = BundleCard("agent-1", "editor", "desc", version, "a" * 64, False)
    coordinator = BundleAgentView(
        "editor",
        {"name": "editor", "future": {"kept": True}},
        "name: editor\nfuture: {kept: true}\n",
    )
    worker = BundleAgentView("alpha", {"name": "alpha"}, "name: alpha\n")
    return BundleDetail(card, coordinator, (worker,))


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.failure: Exception | None = None

    def _result(self, name: str, value: Any, payload: Any = None) -> Any:
        self.calls.append((name, payload))
        if self.failure is not None:
            raise self.failure
        return value

    def list(self, **kwargs: Any) -> BundlePage:
        card = _detail().card
        return self._result("list", BundlePage((card,), card.id, card.id), kwargs)

    def get(self, agent_id: str) -> BundleDetail:
        return self._result("get", _detail(), agent_id)

    def create(self, **kwargs: Any) -> BundleCard:
        return self._result("create", _detail().card, kwargs)

    def update(self, agent_id: str, **kwargs: Any) -> BundleDetail:
        return self._result("update", _detail(2), (agent_id, kwargs))

    def delete(self, agent_id: str) -> None:
        self._result("delete", None, agent_id)

    def validate(self, bundle: bytes) -> BundleValidationResult:
        return self._result("validate", BundleValidationResult(True), bundle)

    def import_bundle(self, bundle: bytes, **kwargs: Any) -> BundleCard:
        return self._result("import", _detail().card, (bundle, kwargs))

    def export(self, agent_id: str) -> bytes:
        return self._result("export", b"bundle-bytes", agent_id)

    def clone(self, agent_id: str, **kwargs: Any) -> BundleCard:
        return self._result("clone", _detail().card, (agent_id, kwargs))

    def create_worker(self, agent_id: str, *args: Any, **kwargs: Any) -> BundleDetail:
        return self._result("create_worker", _detail(2), (agent_id, args, kwargs))

    def update_worker(self, agent_id: str, *args: Any, **kwargs: Any) -> BundleDetail:
        return self._result("update_worker", _detail(2), (agent_id, args, kwargs))

    def delete_worker(self, agent_id: str, *args: Any, **kwargs: Any) -> BundleDetail:
        return self._result("delete_worker", _detail(2), (agent_id, args, kwargs))

    def reorder_workers(self, agent_id: str, *args: Any, **kwargs: Any) -> BundleDetail:
        return self._result("reorder_workers", _detail(2), (agent_id, args, kwargs))


def _client(service: FakeService) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_agent_bundles_router(
            service,  # type: ignore[arg-type]
            options_provider=lambda: {
                "harnesses": [{"id": "real-harness", "label": "Real"}],
                "models": [],
            },
        ),
        prefix="/v1",
    )
    return TestClient(app)


def test_static_metadata_and_validate_routes_are_not_captured_as_agent_ids() -> None:
    service = FakeService()
    client = _client(service)

    options = client.get("/v1/agent-bundles/options")
    validation = client.post(
        "/v1/agent-bundles/validate",
        json={"bundle_base64": base64.b64encode(b"candidate").decode()},
    )

    assert options.status_code == 200
    assert options.json()["harnesses"][0]["id"] == "real-harness"
    assert options.json()["models"] == []
    assert validation.status_code == 200
    assert validation.json() == {"valid": True, "diagnostics": []}
    assert service.calls == [("validate", b"candidate")]


def test_options_expose_skills_from_the_shared_inventory_reader() -> None:
    service = FakeService()

    class FakeSkillsReader:
        def load(self, *, refresh: bool = False) -> SkillSnapshot:
            assert refresh is False
            return SkillSnapshot(
                source=SkillRepositorySource(
                    remote_url="https://git.example.test/skills.git",
                    ref="feature-skills",
                    skills_path="skills",
                    commit_sha="a" * 40,
                    synced_at=1,
                    sync_status="current",
                    error=None,
                ),
                skills=[
                    SkillRecord(
                        id="skill-1",
                        name="review-helper",
                        description="Review a change safely.",
                        relative_path="skills/review-helper",
                        validation_status="valid",
                        diagnostics=[],
                        files=[],
                    ),
                    SkillRecord(
                        id="skill-invalid",
                        name="duplicate-helper",
                        description="Ambiguous duplicate.",
                        relative_path="skills/duplicate-helper",
                        validation_status="error",
                        diagnostics=["Duplicate skill name: duplicate-helper"],
                        files=[],
                    ),
                ],
            )

    app = FastAPI()
    app.include_router(
        create_agent_bundles_router(
            service,  # type: ignore[arg-type]
            options_provider=lambda: {
                "harnesses": [{"id": "real-harness", "label": "Real"}],
            },
            skills_reader=FakeSkillsReader(),  # type: ignore[arg-type]
        ),
        prefix="/v1",
    )

    response = TestClient(app).get("/v1/agent-bundles/options")

    assert response.status_code == 200
    assert response.json()["skills"] == [
        {
            "id": "skill-1",
            "object": "skill",
            "name": "review-helper",
            "description": "Review a change safely.",
            "relative_path": "skills/review-helper",
            "validation_status": "valid",
            "diagnostics": [],
            "file_count": 0,
        }
    ]


def test_crud_clone_import_and_export_routes_use_service_contract() -> None:
    service = FakeService()
    client = _client(service)

    assert client.get("/v1/agent-bundles").status_code == 200
    assert client.get("/v1/agent-bundles/agent-1").json()["coordinator"]["config"]["future"] == {
        "kept": True
    }
    assert (
        client.post(
            "/v1/agent-bundles",
            json={
                "name": "editor",
                "config": {
                    "executor": {
                        "type": "omnigent",
                        "config": {"harness": "real-harness"},
                    },
                    "future": "kept",
                },
            },
        ).status_code
        == 201
    )
    assert (
        client.put(
            "/v1/agent-bundles/agent-1",
            json={"expected_version": 1, "coordinator_changes": {"prompt": "new"}},
        ).json()["card"]["version"]
        == 2
    )
    assert (
        client.post(
            "/v1/agent-bundles/agent-1/clone",
            json={"name": "copy"},
        ).status_code
        == 201
    )
    imported = client.post(
        "/v1/agent-bundles/import",
        data={"name": "uploaded"},
        files={"bundle": ("agent.tar.gz", b"uploaded-bytes", "application/gzip")},
    )
    assert imported.status_code == 201
    exported = client.get("/v1/agent-bundles/agent-1/export")
    assert exported.content == b"bundle-bytes"
    assert exported.headers["content-type"] == "application/gzip"
    assert client.delete("/v1/agent-bundles/agent-1").status_code == 204


def test_worker_create_update_delete_and_order_routes() -> None:
    service = FakeService()
    client = _client(service)

    created = client.post(
        "/v1/agent-bundles/agent-1/workers",
        json={"expected_version": 1, "name": "beta", "config": {"prompt": "hi"}},
    )
    updated = client.put(
        "/v1/agent-bundles/agent-1/workers/alpha",
        json={"expected_version": 1, "changes": {"prompt": "new"}},
    )
    deleted = client.request(
        "DELETE",
        "/v1/agent-bundles/agent-1/workers/alpha",
        json={
            "expected_version": 1,
            "confirmed_references": ["agents/beta/config.yaml#/delegate_to"],
        },
    )
    reordered = client.put(
        "/v1/agent-bundles/agent-1/workers/order",
        json={"expected_version": 1, "names": ["alpha"]},
    )

    assert [response.status_code for response in (created, updated, deleted, reordered)] == [
        201,
        200,
        200,
        200,
    ]
    assert [call[0] for call in service.calls] == [
        "create_worker",
        "update_worker",
        "delete_worker",
        "reorder_workers",
    ]
    assert service.calls[2][1][2]["confirmed_references"] == [
        "agents/beta/config.yaml#/delegate_to"
    ]


def test_update_passes_worker_delete_reference_confirmation_to_service() -> None:
    service = FakeService()
    client = _client(service)

    response = client.put(
        "/v1/agent-bundles/agent-1",
        json={
            "expected_version": 1,
            "worker_operations": [
                {
                    "op": "delete",
                    "name": "alpha",
                    "confirmed_references": ["agents/beta/config.yaml#/delegate_to"],
                }
            ],
        },
    )

    assert response.status_code == 200
    operation = service.calls[0][1][1]["worker_operations"][0]
    assert operation.confirmed_references == ("agents/beta/config.yaml#/delegate_to",)


def test_errors_are_structured_and_do_not_expose_bundle_source() -> None:
    service = FakeService()
    client = _client(service)
    service.failure = BundleValidationFailure(
        (
            BundleIssue(
                "invalid_yaml",
                "invalid YAML",
                file="config.yaml",
                path=None,
                line=3,
                column=2,
            ),
        )
    )

    response = client.put(
        "/v1/agent-bundles/agent-1",
        json={
            "expected_version": 1,
            "advanced_yaml": "secret bundle source: [",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_bundle",
        "diagnostics": [
            {
                "severity": "error",
                "code": "invalid_yaml",
                "message": "invalid YAML",
                "file": "config.yaml",
                "path": None,
                "line": 3,
                "column": 2,
                "agent": None,
                "worker": None,
                "summary_key": None,
            }
        ],
    }
    assert "secret bundle source" not in response.text


def test_oversized_agent_config_error_response_is_structured_and_bounded() -> None:
    service = FakeService()
    client = _client(service)
    service.failure = BundleValidationFailure(
        (
            BundleIssue(
                "agent_config_too_large",
                "agent configuration exceeds the safe response limit",
                file="agents/alpha/config.yaml",
            ),
        )
    )

    response = client.get("/v1/agent-bundles/agent-1")

    assert response.status_code == 400
    assert len(response.content) < 1024
    assert response.json()["detail"]["diagnostics"][0] == {
        "severity": "error",
        "code": "agent_config_too_large",
        "file": "agents/alpha/config.yaml",
        "path": None,
        "line": None,
        "column": None,
        "agent": None,
        "worker": None,
        "message": "agent configuration exceeds the safe response limit",
        "summary_key": None,
    }


def test_conflict_not_found_and_readonly_errors_have_stable_status_codes() -> None:
    service = FakeService()
    client = _client(service)

    service.failure = AgentVersionConflict("agent-1", 1, 2)
    conflict = client.put(
        "/v1/agent-bundles/agent-1",
        json={"expected_version": 1},
    )
    service.failure = KeyError("invisible workspace row")
    missing = client.get("/v1/agent-bundles/agent-1")
    service.failure = PermissionError("built-in Polly is read-only")
    readonly = client.delete("/v1/agent-bundles/agent-1")

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "version_conflict",
        "expected": 1,
        "actual": 2,
    }
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "not_found"}
    assert readonly.status_code == 403
    assert readonly.json()["detail"] == {"code": "read_only"}
