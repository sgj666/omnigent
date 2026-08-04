"""Agent Bundle application service tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from omnigent.agent_bundles import BundleDocument
from omnigent.agent_bundles.service import AgentBundleService, BundleValidationFailure
from omnigent.db.utils import builtin_agent_id
from omnigent.entities import Agent, PagedList
from omnigent.stores.agent_store import AgentVersionConflict


class MemoryArtifacts:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.data[key] = data

    def get(self, key: str) -> bytes:
        if key not in self.data:
            raise KeyError(key)
        return self.data[key]

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.data


class MemoryAgents:
    def __init__(self) -> None:
        self.data: dict[str, Agent] = {}
        self.force_conflict = False

    def create(
        self,
        agent_id: str,
        name: str,
        bundle_location: str,
        description: str | None = None,
    ) -> Agent:
        agent = Agent(agent_id, 1, name, bundle_location, description=description)
        self.data[agent_id] = agent
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self.data.get(agent_id)

    def get_by_name(self, name: str) -> Agent | None:
        return next((agent for agent in self.data.values() if agent.name == name), None)

    def list(self, **kwargs: object) -> PagedList[Agent]:
        del kwargs
        values = list(self.data.values())
        return PagedList(
            data=values,
            first_id=values[0].id if values else None,
            last_id=values[-1].id if values else None,
        )

    def update_template(
        self,
        agent_id: str,
        bundle_location: str,
        name: str,
        description: str | None,
        expected_version: int,
    ) -> Agent | None:
        current = self.data.get(agent_id)
        if current is None:
            return None
        if self.force_conflict or current.version != expected_version:
            raise AgentVersionConflict(agent_id, expected_version, current.version)
        updated = replace(
            current,
            name=name,
            description=description,
            bundle_location=bundle_location,
            version=current.version + 1,
            updated_at=current.created_at + 1,
        )
        self.data[agent_id] = updated
        return updated

    def delete(self, agent_id: str) -> bool:
        return self.data.pop(agent_id, None) is not None


def _bundle(name: str = "editable", *, worker: bool = False) -> bytes:
    files = {
        "config.yaml": (
            "spec_version: 1\n"
            f"name: {name}\n"
            "description: initial\n"
            "future_root: keep # ROOT COMMENT\n"
            "executor:\n"
            "  type: omnigent\n"
            "  config:\n"
            "    harness: claude-sdk\n"
            "prompt: hello\n" + ("tools:\n  agents: [alpha]\n" if worker else "")
        ).encode()
    }
    if worker:
        files["agents/alpha/config.yaml"] = (
            b"spec_version: 1\n"
            b"name: alpha\n"
            b"future_worker: keep # WORKER COMMENT\n"
            b"executor:\n"
            b"  type: omnigent\n"
            b"  config:\n"
            b"    harness: claude-sdk\n"
        )
    return BundleDocument(files).to_bytes()


def _service() -> tuple[AgentBundleService, MemoryAgents, MemoryArtifacts]:
    agents = MemoryAgents()
    artifacts = MemoryArtifacts()
    service = AgentBundleService(agents, artifacts)  # type: ignore[arg-type]
    return service, agents, artifacts


def test_create_get_update_and_export_are_content_addressed() -> None:
    service, agents, artifacts = _service()

    created = service.import_bundle(_bundle(), name="editable")
    detail = service.get(created.id)
    exported = service.export(created.id)
    old_location = agents.data[created.id].bundle_location

    assert detail.card.version == 1
    assert detail.coordinator.config["future_root"] == "keep"
    assert exported == artifacts.data[old_location]

    updated = service.update(
        created.id,
        expected_version=1,
        coordinator_changes={"description": "changed", "timers": {"enabled": True}},
    )

    assert updated.card.version == 2
    assert updated.card.digest != created.digest
    assert agents.data[created.id].bundle_location != old_location
    assert "# ROOT COMMENT" in updated.coordinator.advanced_yaml
    assert updated.coordinator.config["future_root"] == "keep"
    assert updated.coordinator.config["timers"] == {"enabled": True}


def test_optimistic_conflict_keeps_unreferenced_artifact_without_dangerous_delete() -> None:
    service, agents, artifacts = _service()
    created = service.import_bundle(_bundle(), name="editable")
    original_location = agents.data[created.id].bundle_location
    agents.force_conflict = True

    with pytest.raises(AgentVersionConflict):
        service.update(
            created.id,
            expected_version=1,
            coordinator_changes={"description": "losing edit"},
        )

    assert agents.data[created.id].bundle_location == original_location
    assert artifacts.exists(original_location)
    assert len(artifacts.data) == 2


def test_invalid_advanced_yaml_returns_structured_error_without_mutation() -> None:
    service, agents, artifacts = _service()
    created = service.import_bundle(_bundle(), name="editable")
    before = dict(artifacts.data)

    with pytest.raises(BundleValidationFailure) as raised:
        service.update(
            created.id,
            expected_version=1,
            advanced_yaml="spec_version: [\nsecret bundle text",
        )

    assert raised.value.issues[0].code == "invalid_yaml"
    assert raised.value.issues[0].line is not None
    assert "secret bundle text" not in str(raised.value)
    assert agents.data[created.id].version == 1
    assert artifacts.data == before


def test_builtin_polly_is_read_only_but_can_be_cloned() -> None:
    service, agents, artifacts = _service()
    polly_id = builtin_agent_id("polly")
    bundle = _bundle("polly")
    location = service.location(polly_id, bundle)
    artifacts.put(location, bundle)
    agents.create(polly_id, "polly", location)

    assert service.get(polly_id).card.readonly
    with pytest.raises(PermissionError, match="read-only"):
        service.delete(polly_id)

    cloned = service.clone(polly_id, name="my-polly")
    assert cloned.name == "my-polly"
    assert not cloned.readonly
    assert service.get(cloned.id).coordinator.config["name"] == "my-polly"


def test_worker_operations_use_agent_version_cas_and_preserve_source() -> None:
    service, agents, _ = _service()
    created = service.import_bundle(_bundle(worker=True), name="editable")

    updated = service.update_worker(
        created.id,
        "alpha",
        {"description": "changed"},
        expected_version=1,
    )

    assert updated.card.version == 2
    assert updated.workers[0].config["future_worker"] == "keep"
    assert "# WORKER COMMENT" in updated.workers[0].advanced_yaml
    assert agents.data[created.id].version == 2


def test_validate_and_import_reject_invalid_bundle_without_leaking_contents() -> None:
    service, agents, artifacts = _service()
    invalid = BundleDocument({"config.yaml": b"spec_version: 1\nname: invalid\n"}).to_bytes()

    result = service.validate(invalid)

    assert not result.valid
    assert result.issues[0].code == "invalid_bundle"
    assert "spec_version" not in result.issues[0].message
    with pytest.raises(BundleValidationFailure):
        service.import_bundle(invalid, name="invalid")
    assert agents.data == {}
    assert artifacts.data == {}


def test_missing_agent_is_not_visible_across_store_workspace_boundary() -> None:
    service, _, _ = _service()

    with pytest.raises(KeyError, match="not found"):
        service.get("agent-from-another-workspace")
