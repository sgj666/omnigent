"""Team harness domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TeamStatus(StrEnum):
    """The lifecycle state of a team."""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class AgentRole(StrEnum):
    """The role an agent profile fulfils in a team."""

    COORDINATOR = "coordinator"
    WORKER = "worker"


@dataclass
class Team:
    """A group of agent profiles that can execute a run."""

    id: str
    name: str
    coordinator_id: str
    status: TeamStatus = TeamStatus.ACTIVE
    worker_profile_ids: list[str] = field(default_factory=list)


@dataclass
class AgentProfile:
    """An agent configuration assigned to a team role."""

    id: str
    name: str
    role: AgentRole
    capabilities: list[str] = field(default_factory=list)
