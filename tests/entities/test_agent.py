"""Tests for agent entity dataclasses."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from omnigent.entities import AgentBundleSnapshot as ExportedAgentBundleSnapshot
from omnigent.entities.agent import Agent, AgentBundleSnapshot


def test_agent_minimal() -> None:
    agent = Agent(
        id="ag_abc123",
        created_at=1700000000,
        name="research-agent",
        bundle_location="ag_abc123/a1b2c3d4",
    )
    assert agent.id == "ag_abc123"
    assert agent.name == "research-agent"
    assert agent.version == 1
    assert agent.description is None
    assert agent.updated_at is None
    assert agent.session_id is None


def test_agent_full() -> None:
    agent = Agent(
        id="ag_xyz",
        created_at=1700000000,
        name="coder",
        bundle_location="ag_xyz/deadbeef",
        version=3,
        description="A coding agent",
        updated_at=1700001000,
        session_id="conv_session1",
    )
    assert agent.version == 3
    assert agent.description == "A coding agent"
    assert agent.updated_at == 1700001000
    assert agent.session_id == "conv_session1"


def test_agent_is_mutable() -> None:
    """Agent is a regular (non-frozen) dataclass — version bumps are allowed."""
    agent = Agent(
        id="ag_1",
        created_at=1,
        name="a",
        bundle_location="ag_1/hash",
    )
    agent.version = 2
    assert agent.version == 2


def test_agent_defaults_independent() -> None:
    """Each Agent gets independent default values."""
    a = Agent(id="ag_a", created_at=1, name="a", bundle_location="a/h")
    b = Agent(id="ag_b", created_at=1, name="b", bundle_location="b/h")
    a.description = "modified"
    assert b.description is None


def test_agent_bundle_snapshot_uses_content_addressed_location() -> None:
    digest = "a" * 64
    agent = Agent(
        id="ag_snapshot",
        created_at=1,
        name="polly-copy",
        bundle_location=f"ag_snapshot/{digest}",
        version=7,
    )

    snapshot = AgentBundleSnapshot.from_agent(agent)

    assert ExportedAgentBundleSnapshot is AgentBundleSnapshot
    assert snapshot.agent_id == "ag_snapshot"
    assert snapshot.bundle_version == 7
    assert snapshot.bundle_digest == digest
    assert snapshot.bundle_location == f"ag_snapshot/{digest}"


def test_agent_bundle_snapshot_from_agent_rejects_uppercase_location_digest() -> None:
    digest = "ABCDEF" * 10 + "ABCD"
    location = f"artifact-prefix/{digest}"
    agent = Agent(
        id="ag_uppercase",
        created_at=1,
        name="uppercase",
        bundle_location=location,
    )

    with pytest.raises(ValueError, match="content-addressed"):
        AgentBundleSnapshot.from_agent(agent)


def test_direct_snapshot_rejects_uppercase_location_digest() -> None:
    location_digest = "ABCDEF" * 10 + "ABCD"

    with pytest.raises(ValueError, match="content-addressed"):
        AgentBundleSnapshot(
            agent_id="ag_direct",
            bundle_version=2,
            bundle_digest=location_digest.lower(),
            bundle_location=f"artifact-prefix/{location_digest}",
        )


def test_direct_snapshot_rejects_uppercase_bundle_digest() -> None:
    digest = "abcdef" * 10 + "abcd"

    with pytest.raises(ValueError, match="bundle_digest"):
        AgentBundleSnapshot(
            agent_id="ag_direct",
            bundle_version=2,
            bundle_digest=digest.upper(),
            bundle_location=f"artifact-prefix/{digest}",
        )


@pytest.mark.parametrize("agent_id", [None, "", 123])
def test_agent_bundle_snapshot_rejects_invalid_agent_id(agent_id: object) -> None:
    digest = "a" * 64

    with pytest.raises(ValueError, match="non-empty string"):
        AgentBundleSnapshot(
            agent_id=agent_id,  # type: ignore[arg-type]
            bundle_version=1,
            bundle_digest=digest,
            bundle_location=f"ag_direct/{digest}",
        )


@pytest.mark.parametrize("version", [0, -1, True, 1.0, "1", None])
def test_agent_bundle_snapshot_direct_constructor_rejects_invalid_version(
    version: object,
) -> None:
    digest = "e" * 64

    with pytest.raises(ValueError, match="positive integer"):
        AgentBundleSnapshot(
            agent_id="ag_direct",
            bundle_version=version,  # type: ignore[arg-type]
            bundle_digest=digest,
            bundle_location=f"ag_direct/{digest}",
        )


@pytest.mark.parametrize(
    "digest",
    ["not-a-digest", "a" * 63, "a" * 65, "g" * 64],
)
def test_agent_bundle_snapshot_direct_constructor_rejects_invalid_digest(digest: str) -> None:
    location_digest = "f" * 64

    with pytest.raises(ValueError, match="bundle_digest"):
        AgentBundleSnapshot(
            agent_id="ag_direct",
            bundle_version=1,
            bundle_digest=digest,
            bundle_location=f"ag_direct/{location_digest}",
        )


@pytest.mark.parametrize(
    "bundle_location",
    ["ag_direct/not-a-digest", f"ag_direct/{'b' * 64}"],
)
def test_agent_bundle_snapshot_direct_constructor_rejects_invalid_location(
    bundle_location: str,
) -> None:
    digest = "a" * 64

    with pytest.raises(ValueError, match="bundle_location"):
        AgentBundleSnapshot(
            agent_id="ag_direct",
            bundle_version=1,
            bundle_digest=digest,
            bundle_location=bundle_location,
        )


@pytest.mark.parametrize("bundle_location", [None, 123])
def test_agent_bundle_snapshot_from_agent_rejects_non_string_location(
    bundle_location: object,
) -> None:
    agent = Agent(
        id="ag_snapshot",
        created_at=1,
        name="broken",
        bundle_location=bundle_location,  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError) as exc_info:
        AgentBundleSnapshot.from_agent(agent)

    assert str(exc_info.value) == "bundle_location is not content-addressed by SHA-256"


@pytest.mark.parametrize("attribute", ["id", "version", "bundle_location"])
def test_agent_bundle_snapshot_from_agent_rejects_missing_instance_attribute(
    attribute: str,
) -> None:
    digest = "a" * 64
    agent = Agent(
        id="ag_snapshot",
        created_at=1,
        name="broken",
        bundle_location=f"ag_snapshot/{digest}",
        version=2,
    )
    delattr(agent, attribute)

    with pytest.raises(ValueError) as exc_info:
        AgentBundleSnapshot.from_agent(agent)

    assert str(exc_info.value) == "agent is missing required snapshot attributes"


def test_agent_bundle_snapshot_from_agent_uses_one_point_in_time_state() -> None:
    old_digest = "a" * 64
    new_digest = "b" * 64
    old_location = f"ag_snapshot/{old_digest}"
    new_location = f"ag_snapshot/{new_digest}"

    class UpdatingAttributes(dict[str, object]):
        def __getitem__(self, key: str) -> object:
            value = super().__getitem__(key)
            if key == "version":
                self["version"] = 2
                self["bundle_location"] = new_location
            return value

        def copy(self) -> dict[str, object]:
            snapshot = super().copy()
            self["version"] = 2
            self["bundle_location"] = new_location
            return snapshot

    agent = Agent(
        id="ag_snapshot",
        created_at=1,
        name="mutable",
        bundle_location=old_location,
        version=1,
    )
    agent.__dict__ = UpdatingAttributes(agent.__dict__)

    snapshot = AgentBundleSnapshot.from_agent(agent)

    assert (
        snapshot.bundle_version,
        snapshot.bundle_digest,
        snapshot.bundle_location,
    ) == (1, old_digest, old_location)
    assert (agent.version, agent.bundle_location) == (2, new_location)


@pytest.mark.parametrize(
    "agent",
    [
        None,
        object(),
        SimpleNamespace(version=1, bundle_location=f"ag_duck/{'a' * 64}"),
        SimpleNamespace(id="ag_duck", bundle_location=f"ag_duck/{'a' * 64}"),
        SimpleNamespace(id="ag_duck", version=1),
        SimpleNamespace(
            id="ag_duck",
            version=1,
            bundle_location=f"ag_duck/{'a' * 64}",
        ),
    ],
    ids=[
        "none",
        "object",
        "missing-id",
        "missing-version",
        "missing-location",
        "complete-duck",
    ],
)
def test_agent_bundle_snapshot_from_agent_rejects_non_agent_inputs(agent: object) -> None:
    with pytest.raises(ValueError, match="agent must be an Agent"):
        AgentBundleSnapshot.from_agent(agent)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bundle_location",
    [
        "ag_snapshot/not-a-digest",
        "ag_snapshot/",
        f"ag_snapshot/{'a' * 63}",
        f"ag_snapshot/{'a' * 65}",
        f"ag_snapshot/{'g' * 64}",
    ],
)
def test_agent_bundle_snapshot_rejects_non_digest_location(bundle_location: str) -> None:
    agent = Agent(
        id="ag_snapshot",
        created_at=1,
        name="broken",
        bundle_location=bundle_location,
    )

    with pytest.raises(ValueError, match="content-addressed"):
        AgentBundleSnapshot.from_agent(agent)


def test_agent_bundle_snapshot_uses_default_agent_version() -> None:
    digest = "b" * 64
    agent = Agent(
        id="ag_default_version",
        created_at=1,
        name="default-version",
        bundle_location=f"ag_default_version/{digest}",
    )

    assert AgentBundleSnapshot.from_agent(agent).bundle_version == 1


@pytest.mark.parametrize("version", [0, -1, True, 1.0, "1", None])
def test_agent_bundle_snapshot_rejects_invalid_version(version: object) -> None:
    digest = "c" * 64
    agent = Agent(
        id="ag_invalid_version",
        created_at=1,
        name="invalid-version",
        bundle_location=f"ag_invalid_version/{digest}",
        version=version,  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="positive integer"):
        AgentBundleSnapshot.from_agent(agent)


def test_agent_bundle_snapshot_is_frozen() -> None:
    digest = "d" * 64
    snapshot = AgentBundleSnapshot.from_agent(
        Agent(
            id="ag_frozen",
            created_at=1,
            name="frozen",
            bundle_location=f"ag_frozen/{digest}",
        )
    )

    with pytest.raises(FrozenInstanceError):
        snapshot.bundle_version = 2  # type: ignore[misc]
