"""Tests for the team harness domain entities."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from omnigent.entities.feishu import (
    FeishuInstallation,
    FeishuInstallationStatus,
    FeishuPairing,
)
from omnigent.entities.run import Attempt, AttemptStatus, Run, RunStatus, Task, TaskStatus
from omnigent.entities.team import AgentProfile, AgentRole, Team, TeamStatus
from omnigent.entities.workspace_bundle import RepositorySpec, WorkspaceBundle


def test_run_new_is_queued_and_keeps_workspace_immutable() -> None:
    run = Run.new(team_id="team-1", workspace_id="workspace-1", source="feishu")

    assert run.team_id == "team-1"
    assert run.workspace_id == "workspace-1"
    assert run.source == "feishu"
    assert run.status is RunStatus.QUEUED
    assert run.id
    with pytest.raises(FrozenInstanceError):
        run.workspace_id = "workspace-2"  # type: ignore[misc]


def test_team_and_agent_profile_defaults_are_independent() -> None:
    team = Team(id="team-1", name="Delivery", coordinator_id="coord")
    profile = AgentProfile(id="worker-1", name="Coder", role=AgentRole.WORKER)
    other = AgentProfile(id="worker-2", name="Reviewer", role=AgentRole.WORKER)

    assert team.status is TeamStatus.ACTIVE
    assert team.worker_profile_ids == []
    assert profile.capabilities == []
    profile.capabilities.append("code")
    assert other.capabilities == []


def test_task_and_attempt_lifecycle_defaults() -> None:
    task = Task(id="task-1", run_id="run-1", title="Implement feature")
    attempt = Attempt(id="attempt-1", task_id=task.id, agent_profile_id="worker-1")

    assert task.status is TaskStatus.PENDING
    assert task.depends_on == []
    assert attempt.status is AttemptStatus.QUEUED


def test_workspace_bundle_preserves_multi_repository_layout() -> None:
    api = RepositorySpec(name="api", path="ass_api")
    web = RepositorySpec(name="web", path="ass_web")
    bundle = WorkspaceBundle(
        id="workspace-1",
        root_path="/workbench/需求",
        repositories=[api, web],
    )

    assert bundle.root_path.endswith("需求")
    assert [(repo.name, repo.path) for repo in bundle.repositories] == [
        ("api", "ass_api"),
        ("web", "ass_web"),
    ]


def test_feishu_pairing_does_not_store_secret() -> None:
    installation = FeishuInstallation(
        id="install-1",
        team_id="team-1",
        app_id="app-1",
    )
    pairing = FeishuPairing(
        id="pair-1",
        agent_profile_id="worker-1",
        installation_id=installation.id,
    )

    assert installation.status is FeishuInstallationStatus.PENDING
    assert not hasattr(pairing, "secret")
