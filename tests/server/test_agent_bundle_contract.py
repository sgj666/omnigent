"""Cross-layer Agent Bundle API contract backed by the real stores."""

from __future__ import annotations

import io
import tarfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omnigent.agent_bundles import BundleDocument
from omnigent.db.utils import builtin_agent_id
from omnigent.server.bundles import validate_agent_bundle


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_create_app_publishes_static_bundle_schema_before_dynamic_id(app: FastAPI) -> None:
    paths = [route.path for route in app.routes]

    schema_index = paths.index("/v1/agent-bundles/schema")
    detail_index = paths.index("/v1/agent-bundles/{agent_id}")

    assert schema_index < detail_index
    assert "/v1/agent-spec/schema" not in paths


def test_real_polly_detail_has_safe_complete_file_tree_and_schema(app: FastAPI) -> None:
    with _client(app) as client:
        response = client.get(f"/v1/agent-bundles/{builtin_agent_id('polly')}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["schema_version"] == "1"
    assert detail["diagnostics"] == []
    assert detail["coordinator"]["path"] == "config.yaml"
    assert detail["coordinator"]["content"].startswith("spec_version: 1")
    assert detail["coordinator"]["data"]["name"] == "polly"
    assert detail["workers"]

    files = {file["path"]: file for file in detail["files"]}
    assert "config.yaml" in files
    assert "skills/fanout/SKILL.md" in files
    assert files["config.yaml"]["encoding"] == "utf-8"
    assert files["config.yaml"]["size"] == len(files["config.yaml"]["content"].encode())
    assert all("secret" not in file for file in detail["files"])


def test_real_polly_list_card_contains_computed_bundle_metadata(app: FastAPI) -> None:
    with _client(app) as client:
        response = client.get("/v1/agent-bundles")

    assert response.status_code == 200, response.text
    polly = next(
        card for card in response.json()["data"] if card["id"] == builtin_agent_id("polly")
    )
    assert polly["harness"] == "claude-sdk"
    assert polly["worker_count"] == 7
    assert polly["skill_count"] >= 3
    assert polly["mcp_count"] == 0
    assert polly["validation_status"] == "valid"
    assert polly["updated_at"] >= 0
    assert polly["builtin"] is True
    assert polly["editable"] is False


def test_clone_worker_and_file_edit_reload_export_parser_roundtrip(app: FastAPI) -> None:
    polly_id = builtin_agent_id("polly")
    with _client(app) as client:
        cloned_response = client.post(
            f"/v1/agent-bundles/{polly_id}/clone",
            json={"name": "polly-contract-copy", "description": "contract fixture"},
        )
        assert cloned_response.status_code == 201
        cloned = cloned_response.json()
        clone_id = cloned["card"]["id"]
        worker = cloned["workers"][0]
        worker_path = worker["path"]
        worker_name = worker["name"]
        text_file_path = "skills/fanout/SKILL.md"
        original_text = next(
            file["content"] for file in cloned["files"] if file["path"] == text_file_path
        )
        edited_text = f"{original_text}\nEdited through the public file-tree contract.\n"

        update_response = client.put(
            f"/v1/agent-bundles/{clone_id}",
            json={
                "expected_version": cloned["version"],
                "patches": [
                    {
                        "file": worker_path,
                        "op": "add",
                        "path": "/description",
                        "value": "edited through the public contract",
                    },
                    {
                        "file": text_file_path,
                        "op": "replace_file",
                        "value": edited_text,
                    },
                ],
            },
        )
        assert update_response.status_code == 200, update_response.text

        reloaded = client.get(f"/v1/agent-bundles/{clone_id}").json()
        reloaded_worker = next(item for item in reloaded["workers"] if item["name"] == worker_name)
        assert reloaded_worker["data"]["description"] == "edited through the public contract"
        assert (
            next(file for file in reloaded["files"] if file["path"] == text_file_path)["content"]
            == edited_text
        )

        exported = client.get(f"/v1/agent-bundles/{clone_id}/export")
        assert exported.status_code == 200
    document = BundleDocument.from_bytes(exported.content)
    assert document.read_text(worker_path).find("edited through the public contract") >= 0
    assert document.read_text(text_file_path).endswith(
        "Edited through the public file-tree contract.\n"
    )
    assert validate_agent_bundle(exported.content).name == "polly-contract-copy"

    with tarfile.open(fileobj=io.BytesIO(exported.content), mode="r:gz") as archive:
        assert text_file_path in {member.name.lstrip("./") for member in archive.getmembers()}
