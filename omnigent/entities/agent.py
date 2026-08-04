"""Agent entity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from omnigent.spec import AgentSpec

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass
class Agent:
    """
    A registered agent.

    :param id: Unique agent identifier, e.g. ``"ag_abc123"``.
    :param created_at: Unix epoch timestamp of creation.
    :param name: Human-readable agent name, e.g.
        ``"research-agent"``. Template agents have unique names;
        session-scoped copies may reuse names across sessions.
    :param bundle_location: Artifact store key for the current bundle,
        e.g. ``"ag_abc123/a1b2c3d4e5f6..."``. Content-addressed
        (SHA-256 hex of the bundle bytes).
    :param version: Monotonic version counter. Starts at 1, incremented
        on each update.
    :param description: Optional free-text description of the agent.
    :param updated_at: Unix epoch timestamp of the last update, or
        ``None`` if the agent has never been updated.
    """

    id: str
    created_at: int
    name: str
    bundle_location: str
    version: int = 1
    description: str | None = None
    updated_at: int | None = None
    session_id: str | None = None  # owning conversation id; None for template agents


@dataclass(frozen=True)
class AgentBundleSnapshot:
    """Immutable identity of the Agent Bundle used by one Session tree."""

    agent_id: str
    bundle_version: int
    bundle_digest: str
    bundle_location: str

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise ValueError("agent_id must be a non-empty string")
        if (
            isinstance(self.bundle_version, bool)
            or not isinstance(self.bundle_version, int)
            or self.bundle_version < 1
        ):
            raise ValueError("agent bundle version must be a positive integer")
        location_digest = (
            self.bundle_location.rsplit("/", 1)[-1]
            if isinstance(self.bundle_location, str)
            else ""
        )
        if _SHA256_RE.fullmatch(location_digest) is None:
            raise ValueError("bundle_location is not content-addressed by SHA-256")
        if (
            not isinstance(self.bundle_digest, str)
            or _SHA256_RE.fullmatch(self.bundle_digest) is None
        ):
            raise ValueError("bundle_digest must be a SHA-256 hexadecimal digest")
        if location_digest != self.bundle_digest:
            raise ValueError("bundle_location digest does not match bundle_digest")

    @classmethod
    def from_agent(cls, agent: Agent) -> AgentBundleSnapshot:
        """Capture a content-addressed Bundle identity from *agent*."""
        if not isinstance(agent, Agent):
            raise ValueError("agent must be an Agent")
        attributes = agent.__dict__.copy()
        if not all(name in attributes for name in ("id", "version", "bundle_location")):
            raise ValueError("agent is missing required snapshot attributes")

        agent_id = attributes["id"]
        bundle_version = attributes["version"]
        bundle_location = attributes["bundle_location"]
        if not isinstance(bundle_location, str):
            raise ValueError("bundle_location is not content-addressed by SHA-256")
        digest = bundle_location.rsplit("/", 1)[-1]
        return cls(
            agent_id=agent_id,
            bundle_version=bundle_version,
            bundle_digest=digest,
            bundle_location=bundle_location,
        )


@dataclass
class LoadedAgent:
    """
    A fully loaded agent — parsed spec plus the extracted working
    directory on disk. Returned by ``AgentCache.load()``.

    :param spec: The parsed agent spec from config.yaml.
    :param workdir: Path to the extracted agent image directory on disk.
    """

    spec: AgentSpec
    workdir: Path
