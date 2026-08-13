"""Git-backed Skills inventory and local draft-management routes."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.skills import (
    ConfigurableSkillRepositoryReader,
    SkillDraftStore,
    SkillFile,
    SkillRecord,
    SkillRepositoryConfigurationError,
    SkillRepositoryReader,
    SkillSnapshot,
    build_skill_dry_run,
)
from omnigent.stores.permission_store import PermissionStore


class SkillDraftFileInput(BaseModel):
    """One complete text file in a local Skill draft."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=512 * 1024)
    size: int | None = Field(default=None, ge=0)


class SaveSkillDraftRequest(BaseModel):
    """Full replacement payload for one owner-scoped local draft."""

    model_config = ConfigDict(extra="forbid")

    files: list[SkillDraftFileInput] = Field(min_length=1, max_length=100)


class UpdateSkillRepositoryConfigRequest(BaseModel):
    """Complete repository source update; an omitted token is preserved."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    ref: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=1024)
    username: str | None = Field(default=None, max_length=256)
    token: str | None = Field(default=None, max_length=16 * 1024)


def create_skills_router(
    reader: SkillRepositoryReader,
    *,
    draft_store: SkillDraftStore | None = None,
    auth_provider: AuthProvider | None = None,
    permission_store: PermissionStore | None = None,
    repository_manager: ConfigurableSkillRepositoryReader | None = None,
) -> APIRouter:
    """Create Skills inventory plus local Draft / Validate / Dry Run routes."""
    router = APIRouter()
    drafts = draft_store or SkillDraftStore.from_environment()

    async def _snapshot(request: Request, *, refresh: bool) -> Any:
        require_user(request, auth_provider)
        return await asyncio.to_thread(reader.load, refresh=refresh)

    async def _can_edit_repository(request: Request) -> bool:
        user_id = require_user(request, auth_provider)
        if permission_store is None:
            return True
        return bool(user_id and await asyncio.to_thread(permission_store.is_admin, user_id))

    async def _require_repository_admin(request: Request) -> None:
        if await _can_edit_repository(request):
            return
        raise OmnigentError(
            "Admin privileges required to manage the Skills repository",
            code=ErrorCode.FORBIDDEN,
        )

    def _repository_config_response(*, editable: bool) -> dict[str, object]:
        if repository_manager is None:
            raise OmnigentError(
                "Skills repository settings are managed by this deployment",
                code=ErrorCode.CONFLICT,
            )
        configured = repository_manager.get_config()
        return {
            "object": "skill_repository_config",
            "url": configured.remote_url,
            "ref": configured.ref,
            "path": configured.skills_path,
            "username": configured.username,
            "token_configured": configured.token is not None,
            "editable": editable,
            "source": "database",
        }

    @staticmethod
    def _skill(snapshot: SkillSnapshot, skill_id: str) -> SkillRecord:
        skill = next((item for item in snapshot.skills if item.id == skill_id), None)
        if skill is None:
            raise OmnigentError("Skill not found", code=ErrorCode.NOT_FOUND)
        return skill

    @router.get("/skills")
    async def list_skills(request: Request) -> dict[str, object]:
        snapshot = await _snapshot(request, refresh=False)
        return snapshot.list_dict()

    @router.post("/skills/sync")
    async def sync_skills(request: Request) -> dict[str, object]:
        snapshot = await _snapshot(request, refresh=True)
        return snapshot.list_dict()

    @router.get("/skills/repository-config")
    async def get_repository_config(request: Request) -> dict[str, object]:
        editable = await _can_edit_repository(request)
        return _repository_config_response(editable=editable)

    @router.put("/skills/repository-config")
    async def update_repository_config(
        request: Request,
        body: UpdateSkillRepositoryConfigRequest,
    ) -> dict[str, object]:
        await _require_repository_admin(request)
        if repository_manager is None:
            raise OmnigentError(
                "Skills repository settings are managed by this deployment",
                code=ErrorCode.CONFLICT,
            )
        preserve_token = "token" not in body.model_fields_set or not body.token
        try:
            await asyncio.to_thread(
                repository_manager.configure,
                remote_url=body.url,
                ref=body.ref,
                skills_path=body.path,
                username=body.username,
                token=body.token,
                preserve_token=preserve_token,
            )
        except SkillRepositoryConfigurationError as exc:
            raise OmnigentError(str(exc), code=ErrorCode.INVALID_INPUT) from exc
        snapshot = await asyncio.to_thread(repository_manager.load, refresh=True)
        return {
            "config": _repository_config_response(editable=True),
            "inventory": snapshot.list_dict(),
        }

    @router.get("/skills/{skill_id}")
    async def get_skill(request: Request, skill_id: str) -> dict[str, Any]:
        snapshot = await _snapshot(request, refresh=False)
        skill = _skill(snapshot, skill_id)
        return {
            **skill.detail_dict(),
            "source": asdict(snapshot.source),
        }

    @router.get("/skills/{skill_id}/draft")
    async def get_skill_draft(request: Request, skill_id: str) -> dict[str, object]:
        owner_user_id = require_user(request, auth_provider)
        snapshot = await asyncio.to_thread(reader.load, refresh=False)
        _skill(snapshot, skill_id)
        draft = await asyncio.to_thread(drafts.get, owner_user_id, skill_id)
        return {
            "draft": draft.to_dict() if draft else None,
            "baseline_current": bool(
                draft is not None and draft.baseline_sha == snapshot.source.commit_sha
            ),
            "publish_enabled": False,
        }

    @router.put("/skills/{skill_id}/draft")
    async def save_skill_draft(
        request: Request,
        skill_id: str,
        body: SaveSkillDraftRequest,
    ) -> dict[str, object]:
        owner_user_id = require_user(request, auth_provider)
        snapshot = await asyncio.to_thread(reader.load, refresh=False)
        skill = _skill(snapshot, skill_id)
        if snapshot.source.commit_sha is None:
            raise OmnigentError(
                "A current repository baseline is required",
                code=ErrorCode.CONFLICT,
            )
        files = [
            SkillFile(
                path=item.path,
                content=item.content,
                size=len(item.content.encode("utf-8")),
            )
            for item in body.files
        ]
        draft = await asyncio.to_thread(
            drafts.save,
            owner_user_id,
            skill,
            snapshot.source.commit_sha,
            files,
        )
        return {
            "draft": draft.to_dict(),
            "baseline_current": True,
            "publish_enabled": False,
        }

    @router.post("/skills/{skill_id}/draft/validate")
    async def validate_skill_draft(request: Request, skill_id: str) -> dict[str, object]:
        owner_user_id = require_user(request, auth_provider)
        snapshot = await asyncio.to_thread(reader.load, refresh=False)
        _skill(snapshot, skill_id)
        draft = await asyncio.to_thread(drafts.get, owner_user_id, skill_id)
        if draft is None:
            raise OmnigentError("Skill draft not found", code=ErrorCode.NOT_FOUND)
        return {
            "validation": asdict(draft.validation),
            "baseline_current": draft.baseline_sha == snapshot.source.commit_sha,
        }

    @router.post("/skills/{skill_id}/draft/dry-run")
    async def dry_run_skill_draft(request: Request, skill_id: str) -> dict[str, object]:
        owner_user_id = require_user(request, auth_provider)
        snapshot = await asyncio.to_thread(reader.load, refresh=True)
        skill = _skill(snapshot, skill_id)
        draft = await asyncio.to_thread(drafts.get, owner_user_id, skill_id)
        if draft is None:
            raise OmnigentError("Skill draft not found", code=ErrorCode.NOT_FOUND)
        if (
            snapshot.source.sync_status != "current"
            or draft.baseline_sha != snapshot.source.commit_sha
        ):
            raise OmnigentError(
                "Skill repository changed since this draft was created",
                code=ErrorCode.CONFLICT,
            )
        result = build_skill_dry_run(skill, draft)
        return {
            **result,
            "remote_url": snapshot.source.remote_url,
            "ref": snapshot.source.ref,
        }

    @router.delete(
        "/skills/{skill_id}/draft",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    async def delete_skill_draft(request: Request, skill_id: str) -> Response:
        owner_user_id = require_user(request, auth_provider)
        snapshot = await asyncio.to_thread(reader.load, refresh=False)
        _skill(snapshot, skill_id)
        await asyncio.to_thread(drafts.delete, owner_user_id, skill_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
