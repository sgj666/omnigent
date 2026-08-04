"""Team-harness routes and their small persistence boundary."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, select

from omnigent.db.db_models import (
    SqlAgentProfile,
    SqlRun,
    SqlTeam,
    SqlTeamMember,
    SqlThreadWorkspaceSelection,
    SqlWorkspaceBundle,
    SqlWorkspaceRepository,
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

    def select_run_workspace(self, run_id: str, workspace_id: str) -> None:
        run = self.runs.get(run_id)
        if run is None:
            raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
        if run["status"] == "running" and run["workspace_id"] != workspace_id:
            raise OmnigentError(
                "Workspace is immutable while a run is running", code=ErrorCode.CONFLICT
            )
        run["workspace_id"] = workspace_id


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
            for repository in session.execute(
                select(SqlWorkspaceRepository).where(
                    SqlWorkspaceRepository.workspace_id == workspace_id
                )
            ).scalars():
                workspace = self.workspaces.get(repository.workspace_bundle_id)
                if workspace is not None:
                    workspace["repositories"].append(
                        {"name": repository.name, "path": repository.path}
                    )
            self.runs = {
                row.id: {
                    "id": row.id,
                    "object": "run",
                    "team_id": row.team_id,
                    "workspace_id": row.workspace_bundle_id,
                    "source": row.source,
                    "status": row.status,
                }
                for row in session.execute(
                    select(SqlRun).where(SqlRun.workspace_id == workspace_id)
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

    def update_team(self, team_id: str, body: UpdateTeamRequest) -> dict[str, Any] | None:
        team = super().update_team(team_id, body)
        if team is None:
            return None
        with self._session() as session:
            row = session.get(SqlTeam, (current_workspace_id(), team_id))
            if row is None:
                return None
            row.name, row.status, row.updated_at = team["name"], team["status"], now_epoch()
            if body.members is not None:
                old_ids = (
                    session.execute(
                        select(SqlTeamMember.agent_profile_id).where(
                            SqlTeamMember.workspace_id == current_workspace_id(),
                            SqlTeamMember.team_id == team_id,
                        )
                    )
                    .scalars()
                    .all()
                )
                session.execute(
                    delete(SqlTeamMember).where(
                        SqlTeamMember.workspace_id == current_workspace_id(),
                        SqlTeamMember.team_id == team_id,
                    )
                )
                session.execute(
                    delete(SqlAgentProfile).where(
                        SqlAgentProfile.workspace_id == current_workspace_id(),
                        SqlAgentProfile.id.in_(old_ids),
                    )
                )
                now = now_epoch()
                for member in [team["coordinator"], *team["workers"]]:
                    session.add(
                        SqlAgentProfile(
                            id=member["id"],
                            name=member["name"],
                            role=member["role"],
                            capabilities=json.dumps(
                                {
                                    k: v
                                    for k, v in member.items()
                                    if k not in {"id", "name", "role"}
                                }
                            ),
                            created_at=now,
                            updated_at=None,
                        )
                    )
                    session.add(
                        SqlTeamMember(
                            id=uuid4().hex,
                            team_id=team_id,
                            agent_profile_id=member["id"],
                            role=member["role"],
                            created_at=now,
                        )
                    )
                row.coordinator_id = team["coordinator"]["id"]
        return team

    def create_run(self, *, team_id: str, thread_id: str, source: str) -> dict[str, Any]:
        run = super().create_run(team_id=team_id, thread_id=thread_id, source=source)
        with self._session() as session:
            session.add(
                SqlRun(
                    id=run["id"],
                    team_id=team_id,
                    workspace_bundle_id=run["workspace_id"],
                    source=source,
                    status="queued",
                    account_id=None,
                    created_at=now_epoch(),
                    updated_at=None,
                )
            )
        return run

    def select_run_workspace(self, run_id: str, workspace_id: str) -> None:
        """Validate and persist a run workspace switch before updating the cache."""
        with self._session() as session:
            row = session.get(SqlRun, (current_workspace_id(), run_id))
            if row is None:
                raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
            if row.status == "running" and row.workspace_bundle_id != workspace_id:
                raise OmnigentError(
                    "Workspace is immutable while a run is running", code=ErrorCode.CONFLICT
                )
            row.workspace_bundle_id = workspace_id
            session.flush()
        self.runs[run_id]["workspace_id"] = workspace_id

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
            for repository in workspace["repositories"]:
                session.add(
                    SqlWorkspaceRepository(
                        id=uuid4().hex,
                        workspace_bundle_id=str(workspace["id"]),
                        name=repository["name"],
                        path=repository["path"],
                        created_at=now_epoch(),
                    )
                )


def create_teams_router(
    store: TeamMemoryStore,
    *,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Build read-only diagnostic endpoints for retired Team records."""
    router = APIRouter()

    def _gone() -> None:
        raise HTTPException(
            status_code=410,
            detail="Legacy Team execution is retired; create and operate a Session-backed Run.",
        )

    @router.post("/teams")
    async def create_team(request: Request) -> None:
        require_user(request, auth_provider)
        _gone()

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
    async def update_team(request: Request, team_id: str) -> None:
        require_user(request, auth_provider)
        del team_id
        _gone()

    @router.delete("/teams/{team_id}")
    async def delete_team(request: Request, team_id: str) -> None:
        require_user(request, auth_provider)
        del team_id
        _gone()

    @router.post("/teams/{team_id}/start")
    async def start_team(request: Request, team_id: str) -> None:
        require_user(request, auth_provider)
        del team_id
        _gone()

    @router.post("/runs/{run_id}/retry")
    async def retry_run(request: Request, run_id: str) -> None:
        require_user(request, auth_provider)
        del run_id
        _gone()

    @router.post("/runs/{run_id}/approve")
    async def approve_run(request: Request, run_id: str) -> None:
        require_user(request, auth_provider)
        del run_id
        _gone()

    @router.post("/runs/{run_id}/assign")
    async def assign_run(request: Request, run_id: str) -> None:
        require_user(request, auth_provider)
        del run_id
        _gone()

    @router.get("/teams/{team_id}/runs")
    async def list_team_runs(request: Request, team_id: str) -> dict[str, Any]:
        require_user(request, auth_provider)
        if store.get_team(team_id) is None:
            raise OmnigentError("Team not found", code=ErrorCode.NOT_FOUND)
        return {
            "object": "list",
            "data": [deepcopy(run) for run in store.runs.values() if run["team_id"] == team_id],
        }

    @router.get("/runs/{run_id}")
    async def get_run(request: Request, run_id: str) -> dict[str, Any]:
        require_user(request, auth_provider)
        run = store.runs.get(run_id)
        if run is None:
            raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
        return deepcopy(run)

    return router
