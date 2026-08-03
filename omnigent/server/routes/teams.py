"""Team-harness routes and their small persistence boundary."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from sqlalchemy import select

from omnigent.db.db_models import (
    SqlAgentProfile,
    SqlTeam,
    SqlTeamMember,
    SqlThreadWorkspaceSelection,
    SqlWorkspaceBundle,
    current_workspace_id,
)
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import CreateTeamRequest, UpdateTeamRequest


class TeamMemoryStore:
    """In-process store used by tests and lightweight API-only deployments.

    The route factory accepts this narrow duck-typed boundary so a SQL-backed
    deployment can replace it without coupling HTTP serialization to storage.
    """

    def __init__(self) -> None:
        self.teams: dict[str, dict[str, Any]] = {}
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.thread_workspaces: dict[str, str] = {}
        self.runs: dict[str, dict[str, Any]] = {}

    def create_team(self, body: CreateTeamRequest) -> dict[str, Any]:
        team_id = uuid4().hex
        members = [member.model_dump() | {"id": uuid4().hex} for member in body.members]
        coordinator = next(member for member in members if member["role"] == "coordinator")
        team = {
            "id": team_id,
            "object": "team",
            "name": body.name,
            "status": "active",
            "coordinator": coordinator,
            "workers": [member for member in members if member["role"] == "worker"],
        }
        self.teams[team_id] = team
        return deepcopy(team)

    def list_teams(self) -> list[dict[str, Any]]:
        return [deepcopy(team) for team in self.teams.values()]

    def get_team(self, team_id: str) -> dict[str, Any] | None:
        team = self.teams.get(team_id)
        return deepcopy(team) if team else None

    def update_team(self, team_id: str, body: UpdateTeamRequest) -> dict[str, Any] | None:
        team = self.teams.get(team_id)
        if team is None:
            return None
        if body.name is not None:
            team["name"] = body.name
        if body.status is not None:
            team["status"] = body.status
        if body.members is not None:
            members = [member.model_dump() | {"id": uuid4().hex} for member in body.members]
            team["coordinator"] = next(
                member for member in members if member["role"] == "coordinator"
            )
            team["workers"] = [member for member in members if member["role"] == "worker"]
        return deepcopy(team)

    def create_run(self, *, team_id: str, thread_id: str, source: str) -> dict[str, Any]:
        workspace_id = self.thread_workspaces.get(thread_id)
        run_id = uuid4().hex
        run = {
            "id": run_id,
            "object": "run",
            "team_id": team_id,
            "workspace_id": workspace_id,
            "source": source,
            "status": "queued",
        }
        self.runs[run_id] = run
        return run


class SqlAlchemyTeamWorkspaceStore(TeamMemoryStore):
    """SQLAlchemy-backed default store for the team and workspace API.

    The in-memory dictionaries remain a test-double-compatible cache, while
    every mutation is written to the workspace-scoped harness tables.
    """

    def __init__(self, storage_location: str) -> None:
        super().__init__()
        self.storage_location = storage_location
        self._session = make_managed_session_maker(get_or_create_engine(storage_location))
        self._load()

    def _load(self) -> None:
        with self._session() as session:
            workspace_id = current_workspace_id()
            profiles = {
                row.id: {
                    "id": row.id,
                    "name": row.name,
                    "role": row.role,
                    **json.loads(row.capabilities or "{}"),
                }
                for row in session.execute(
                    select(SqlAgentProfile).where(SqlAgentProfile.workspace_id == workspace_id)
                ).scalars()
            }
            memberships: dict[str, list[dict[str, Any]]] = {}
            for member in session.execute(
                select(SqlTeamMember).where(SqlTeamMember.workspace_id == workspace_id)
            ).scalars():
                if member.agent_profile_id in profiles:
                    memberships.setdefault(member.team_id, []).append(
                        profiles[member.agent_profile_id]
                    )
            for row in session.execute(
                select(SqlTeam).where(SqlTeam.workspace_id == workspace_id)
            ).scalars():
                members = memberships.get(row.id, [])
                coordinator = next((m for m in members if m["id"] == row.coordinator_id), None)
                if coordinator is not None:
                    self.teams[row.id] = {
                        "id": row.id,
                        "object": "team",
                        "name": row.name,
                        "status": row.status,
                        "coordinator": coordinator,
                        "workers": [m for m in members if m["role"] == "worker"],
                    }
            self.workspaces = {
                row.id: {
                    "id": row.id,
                    "object": "workspace",
                    "root_path": row.root_path,
                    "repositories": [],
                }
                for row in session.execute(
                    select(SqlWorkspaceBundle).where(
                        SqlWorkspaceBundle.workspace_id == workspace_id
                    )
                ).scalars()
            }
            self.thread_workspaces = {
                row.thread_id: row.selected_workspace_id
                for row in session.execute(
                    select(SqlThreadWorkspaceSelection).where(
                        SqlThreadWorkspaceSelection.workspace_id == workspace_id,
                        SqlThreadWorkspaceSelection.scope == "",
                    )
                ).scalars()
            }

    def create_team(self, body: CreateTeamRequest) -> dict[str, Any]:
        team = super().create_team(body)
        with self._session() as session:
            now = now_epoch()
            members = [team["coordinator"], *team["workers"]]
            for member in members:
                session.add(
                    SqlAgentProfile(
                        id=member["id"],
                        name=member["name"],
                        role=member["role"],
                        capabilities=json.dumps(
                            {k: v for k, v in member.items() if k not in {"id", "name", "role"}}
                        ),
                        created_at=now,
                        updated_at=None,
                    )
                )
                session.add(
                    SqlTeamMember(
                        id=uuid4().hex,
                        team_id=team["id"],
                        agent_profile_id=member["id"],
                        role=member["role"],
                        created_at=now,
                    )
                )
            session.add(
                SqlTeam(
                    id=team["id"],
                    name=team["name"],
                    coordinator_id=team["coordinator"]["id"],
                    status=team["status"],
                    created_at=now,
                    updated_at=None,
                )
            )
        return team

    def select_thread_workspace(self, thread_id: str, workspace_id: str) -> None:
        self.thread_workspaces[thread_id] = workspace_id
        with self._session() as session:
            key = (current_workspace_id(), thread_id, "")
            row = session.get(SqlThreadWorkspaceSelection, key)
            if row is None:
                session.add(
                    SqlThreadWorkspaceSelection(
                        thread_id=thread_id,
                        scope="",
                        selected_workspace_id=workspace_id,
                        created_at=now_epoch(),
                        updated_at=None,
                    )
                )
            else:
                row.selected_workspace_id = workspace_id
                row.updated_at = now_epoch()

    def persist_workspace(self, workspace: dict[str, Any]) -> None:
        with self._session() as session:
            session.add(
                SqlWorkspaceBundle(
                    id=str(workspace["id"]),
                    root_path=str(workspace["root_path"]),
                    created_at=now_epoch(),
                )
            )


def create_teams_router(
    store: TeamMemoryStore,
    *,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Build CRUD and run-list endpoints for team-harness teams."""
    router = APIRouter()

    @router.post("/teams")
    async def create_team(request: Request, body: CreateTeamRequest) -> dict[str, Any]:
        require_user(request, auth_provider)
        return store.create_team(body)

    @router.get("/teams")
    async def list_teams(request: Request) -> dict[str, Any]:
        require_user(request, auth_provider)
        return {"object": "list", "data": store.list_teams()}

    @router.get("/teams/{team_id}")
    async def get_team(request: Request, team_id: str) -> dict[str, Any]:
        require_user(request, auth_provider)
        team = store.get_team(team_id)
        if team is None:
            raise OmnigentError("Team not found", code=ErrorCode.NOT_FOUND)
        return team

    @router.patch("/teams/{team_id}")
    async def update_team(
        request: Request, team_id: str, body: UpdateTeamRequest
    ) -> dict[str, Any]:
        require_user(request, auth_provider)
        team = store.update_team(team_id, body)
        if team is None:
            raise OmnigentError("Team not found", code=ErrorCode.NOT_FOUND)
        return team

    @router.get("/teams/{team_id}/runs")
    async def list_team_runs(request: Request, team_id: str) -> dict[str, Any]:
        require_user(request, auth_provider)
        if store.get_team(team_id) is None:
            raise OmnigentError("Team not found", code=ErrorCode.NOT_FOUND)
        return {
            "object": "list",
            "data": [deepcopy(run) for run in store.runs.values() if run["team_id"] == team_id],
        }

    return router
