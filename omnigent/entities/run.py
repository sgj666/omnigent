"""Run, task, and attempt entities for the team harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4


class RunStatus(StrEnum):
    """The lifecycle state of a run."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    """The lifecycle state of a task within a run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AttemptStatus(StrEnum):
    """The lifecycle state of a task execution attempt."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Run:
    """An immutable request to execute a team's work in one workspace."""

    id: str
    team_id: str
    workspace_id: str
    source: str
    status: RunStatus = RunStatus.QUEUED

    @classmethod
    def new(cls, team_id: str, workspace_id: str, source: str) -> Run:
        """Create a queued run with a generated identifier."""

        return cls(
            id=uuid4().hex,
            team_id=team_id,
            workspace_id=workspace_id,
            source=source,
        )


@dataclass
class Task:
    """A unit of work in a run."""

    id: str
    run_id: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Attempt:
    """One attempt to have an agent profile execute a task."""

    id: str
    task_id: str
    agent_profile_id: str
    status: AttemptStatus = AttemptStatus.QUEUED
