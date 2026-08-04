"""Lossless coordinator and worker edits for Agent Bundles."""

from __future__ import annotations

import pytest

from omnigent.agent_bundles import BundleDocument
from omnigent.agent_bundles.workers import BundleWorkers


def _document() -> BundleDocument:
    return BundleDocument(
        {
            "config.yaml": (
                b"spec_version: 1\n"
                b"name: coordinator\n"
                b"unknown_root: keep # ROOT COMMENT\n"
                b"executor:\n"
                b"  type: omnigent\n"
                b"  config:\n"
                b"    harness: claude-sdk\n"
                b"tools:\n"
                b"  unknown_tools: keep\n"
                b"  agents: [alpha]\n"
            ),
            "agents/alpha/config.yaml": (
                b"spec_version: 1\n"
                b"name: alpha\n"
                b"description: old # WORKER COMMENT\n"
                b"unknown_worker: keep\n"
                b"executor:\n"
                b"  type: omnigent\n"
                b"  config:\n"
                b"    harness: codex-native\n"
            ),
            "agents/alpha/AGENTS.md": b"Alpha instructions.\n",
        }
    )


def test_create_worker_uses_official_roster_and_omits_default_model() -> None:
    document = _document()

    BundleWorkers.create(
        document,
        "Beta_2",
        {
            "spec_version": 1,
            "description": "new worker",
            "executor": {
                "type": "omnigent",
                "config": {"harness": "claude-native"},
            },
            "future_field": {"enabled": True},
        },
    )

    assert BundleWorkers.names(document) == ["alpha", "Beta_2"]
    worker = BundleWorkers.get(document, "Beta_2")
    assert worker.config["name"] == "Beta_2"
    assert worker.config["future_field"] == {"enabled": True}
    assert "model" not in worker.config
    assert "model" not in worker.config["executor"]
    assert "# ROOT COMMENT" in document.read_text("config.yaml")
    assert document.yaml_value("config.yaml", ["tools", "unknown_tools"]) == "keep"


@pytest.mark.parametrize("name", ["", "has space", "slash/name", "dot.name", "中文"])
def test_invalid_worker_name_is_rejected_atomically(name: str) -> None:
    document = _document()
    before = document.to_bytes()

    with pytest.raises(ValueError, match="worker name"):
        BundleWorkers.create(document, name, {"spec_version": 1})

    assert document.to_bytes() == before


def test_worker_update_and_reorder_preserve_unknown_fields_and_comments() -> None:
    document = _document()
    BundleWorkers.create(document, "beta", {"spec_version": 1})

    BundleWorkers.update(document, "alpha", {"description": "updated", "spawn": True})
    BundleWorkers.reorder(document, ["beta", "alpha"])

    assert BundleWorkers.names(document) == ["beta", "alpha"]
    alpha = BundleWorkers.get(document, "alpha")
    assert alpha.config["description"] == "updated"
    assert alpha.config["spawn"] is True
    assert alpha.config["unknown_worker"] == "keep"
    assert "# WORKER COMMENT" in alpha.advanced_yaml
    assert "model" not in alpha.config["executor"]


def test_delete_worker_removes_its_tree_and_roster_entry() -> None:
    document = _document()

    BundleWorkers.delete(document, "alpha")

    assert BundleWorkers.names(document) == []
    assert not any(path.startswith("agents/alpha/") for path in document.paths())
    assert "unknown_tools: keep" in document.read_text("config.yaml")


def test_coordinator_update_preserves_unknown_fields_and_comments() -> None:
    document = _document()

    BundleWorkers.update_coordinator(
        document,
        {"description": "updated coordinator", "timers": {"enabled": True}},
    )

    coordinator = BundleWorkers.coordinator(document)
    assert coordinator.config["description"] == "updated coordinator"
    assert coordinator.config["timers"] == {"enabled": True}
    assert coordinator.config["unknown_root"] == "keep"
    assert "# ROOT COMMENT" in coordinator.advanced_yaml


def test_reorder_requires_exact_worker_set_atomically() -> None:
    document = _document()
    before = document.to_bytes()

    with pytest.raises(ValueError, match="exactly once"):
        BundleWorkers.reorder(document, ["alpha", "missing"])

    assert document.to_bytes() == before
