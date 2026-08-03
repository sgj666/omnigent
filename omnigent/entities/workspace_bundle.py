"""Workspace bundle entities for team runs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RepositorySpec:
    """A repository mounted in a workspace bundle."""

    name: str
    path: str


@dataclass
class WorkspaceBundle:
    """The workspace and repositories made available to a run."""

    id: str
    root_path: str
    repositories: list[RepositorySpec] = field(default_factory=list)
