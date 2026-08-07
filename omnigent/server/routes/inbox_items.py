"""Owner-private persistent product Inbox routes."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request

from omnigent.entities import InboxItem
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runtime import user_session_stream
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import UpdateInboxItemRequest
from omnigent.stores.inbox_item_store import InboxItemStore
from omnigent.stores.work_item_run_store import WorkItemRunStore
from omnigent.stores.work_item_store import WorkItemStore
from omnigent.work_lifecycle import TaskRunState, TaskState


def _response(item: InboxItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "object": "inbox_item",
        "kind": item.kind.value,
        "work_item_id": item.work_item_id,
        "work_item_run_id": item.work_item_run_id,
        "session_id": item.session_id,
        "source_id": item.source_id,
        "message": item.message,
        "target_url": item.target_url,
        "action_required": item.action_required,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "read_at": item.read_at,
        "resolved_at": item.resolved_at,
    }


def _announce(user_id: str | None) -> None:
    user_session_stream.publish(user_session_stream.user_key(user_id), {"type": "inbox_changed"})


def _owner_dedupe_key(owner_user_id: str | None, event_key: str) -> str:
    return f"{owner_user_id or 'local'}:{event_key}"


def _repair_task_projections(
    inbox_item_store: InboxItemStore,
    work_item_store: WorkItemStore,
    work_item_run_store: WorkItemRunStore,
    *,
    owner_user_id: str | None,
) -> None:
    """Rebuild missing Task lifecycle projections from durable state."""
    for task in work_item_store.list(owner_user_id=owner_user_id):
        if task.state is TaskState.DONE:
            # Rows completed before ``completion_id`` was introduced retain
            # their historical version-based projection. Recognize any such
            # projection instead of creating a one-time duplicate on upgrade.
            has_legacy_projection = (
                task.completion_id is None
                and inbox_item_store.has_task_completion(
                    task.id,
                    owner_user_id=owner_user_id,
                )
            )
            if not has_legacy_projection:
                occurrence = task.completion_id or f"legacy-v{task.version}"
                inbox_item_store.create_if_absent(
                    uuid.uuid4().hex,
                    owner_user_id=owner_user_id,
                    kind="task_completed",
                    dedupe_key=_owner_dedupe_key(
                        owner_user_id,
                        f"work-item:{task.id}:completed:{occurrence}",
                    ),
                    work_item_id=task.id,
                    message=task.title,
                    target_url=f"/tasks/{task.id}",
                )

        for run in work_item_run_store.list_for_work_item(
            task.id,
            owner_user_id=owner_user_id,
        ):
            projection = {
                TaskRunState.WAITING: ("task_waiting", True),
                TaskRunState.SUCCEEDED: ("task_succeeded", False),
                TaskRunState.FAILED: ("task_failed", True),
                TaskRunState.CANCELLED: ("task_cancelled", False),
            }.get(run.state)
            if projection is None:
                continue
            kind, action_required = projection
            inbox_item_store.create_if_absent(
                uuid.uuid4().hex,
                owner_user_id=owner_user_id,
                kind=kind,
                dedupe_key=_owner_dedupe_key(
                    owner_user_id,
                    f"work-item-run:{run.id}:{run.state.value}",
                ),
                work_item_id=task.id,
                work_item_run_id=run.id,
                session_id=run.session_id,
                message=task.title,
                target_url=f"/tasks/{task.id}",
                action_required=action_required,
            )


def create_inbox_items_router(
    inbox_item_store: InboxItemStore,
    *,
    work_item_store: WorkItemStore | None = None,
    work_item_run_store: WorkItemRunStore | None = None,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Create persistent Inbox list and read-state routes."""
    router = APIRouter()

    @router.get("/inbox-items")
    async def list_inbox_items(
        request: Request,
        unread_only: bool = False,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        user_id = require_user(request, auth_provider)
        if work_item_store is not None and work_item_run_store is not None:
            await asyncio.to_thread(
                _repair_task_projections,
                inbox_item_store,
                work_item_store,
                work_item_run_store,
                owner_user_id=user_id,
            )
        items, unread_count = await asyncio.gather(
            asyncio.to_thread(
                inbox_item_store.list,
                owner_user_id=user_id,
                unread_only=unread_only,
                limit=limit,
            ),
            asyncio.to_thread(inbox_item_store.count_unread, owner_user_id=user_id),
        )
        return {
            "object": "list",
            "data": [_response(item) for item in items],
            "unread_count": unread_count,
        }

    @router.patch("/inbox-items/{item_id}")
    async def update_inbox_item(
        request: Request,
        item_id: str,
        body: UpdateInboxItemRequest,
    ) -> dict[str, Any]:
        user_id = require_user(request, auth_provider)
        item = await asyncio.to_thread(
            inbox_item_store.set_read,
            item_id,
            owner_user_id=user_id,
            read=body.read,
        )
        if item is None:
            raise OmnigentError("Inbox item not found", code=ErrorCode.NOT_FOUND)
        _announce(user_id)
        return _response(item)

    @router.post("/inbox-items/read-all")
    async def mark_all_inbox_items_read(request: Request) -> dict[str, int]:
        user_id = require_user(request, auth_provider)
        updated = await asyncio.to_thread(
            inbox_item_store.mark_all_read,
            owner_user_id=user_id,
        )
        if updated:
            _announce(user_id)
        return {"updated": updated}

    return router
