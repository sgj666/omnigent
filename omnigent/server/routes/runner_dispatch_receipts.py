"""Internal durable runner-dispatch receipt API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from omnigent.db.db_models import workspace_scope
from omnigent.runner.identity import (
    RUNNER_ID_HEADER,
    RUNNER_TUNNEL_TOKEN_HEADER,
    token_bound_runner_id,
)
from omnigent.stores import ConversationStore

_logger = logging.getLogger(__name__)
_INDETERMINATE_FAILURE_CODE = "runner_restarted_during_execution"


async def _apply_pending_effects(
    conversation_store: ConversationStore,
    receipt: dict[str, Any],
    callback: Callable[[dict[str, Any]], Awaitable[None]],
) -> dict[str, Any]:
    """Apply one durable effects entry, retaining it on any failure."""
    if receipt.get("effects_status") != "pending":
        return receipt
    conversation_id = receipt["conversation_id"]
    idempotency_key = receipt["idempotency_key"]
    try:
        await callback(receipt)
    except Exception as exc:  # noqa: BLE001 - durable outbox retries every failure
        _logger.warning(
            "Runner dispatch terminal effects remain pending for %s/%s",
            conversation_id,
            idempotency_key,
            exc_info=True,
        )
        failed = await asyncio.to_thread(
            conversation_store.record_runner_dispatch_effect_failure,
            conversation_id,
            idempotency_key=idempotency_key,
            error=str(exc) or type(exc).__name__,
        )
        return failed or receipt
    try:
        completed = await asyncio.to_thread(
            conversation_store.complete_runner_dispatch_effects,
            conversation_id,
            idempotency_key=idempotency_key,
        )
    except Exception:  # noqa: BLE001 - a fresh maintenance cycle retries the pending row
        _logger.warning(
            "Runner dispatch effects completed but durable completion remains pending for %s/%s",
            conversation_id,
            idempotency_key,
            exc_info=True,
        )
        return receipt
    return completed or receipt


async def drain_pending_runner_dispatch_effects(
    conversation_store: ConversationStore,
    callback: Callable[[dict[str, Any]], Awaitable[None]],
) -> list[dict[str, Any]]:
    """Replay every durable terminal-effects entry still marked pending."""
    receipts = await asyncio.to_thread(
        conversation_store.list_pending_runner_dispatch_effects,
    )
    return [
        await _apply_pending_effects(conversation_store, receipt, callback) for receipt in receipts
    ]


async def drain_all_pending_runner_dispatch_effects(
    conversation_store: ConversationStore,
    callback: Callable[[dict[str, Any]], Awaitable[None]],
) -> list[dict[str, Any]]:
    """Drain pending effects in every tenant without leaking workspace scope."""
    workspace_ids = await asyncio.to_thread(
        conversation_store.list_pending_runner_dispatch_effect_workspace_ids,
    )
    drained: list[dict[str, Any]] = []
    for workspace_id in workspace_ids:
        try:
            with workspace_scope(workspace_id):
                drained.extend(
                    await drain_pending_runner_dispatch_effects(
                        conversation_store,
                        callback,
                    )
                )
        except Exception:  # noqa: BLE001 - one tenant must not block another
            _logger.warning(
                "Runner dispatch effects drain failed for workspace %s",
                workspace_id,
                exc_info=True,
            )
    return drained


async def maintain_pending_runner_dispatch_effects(
    conversation_store: ConversationStore,
    callback: Callable[[dict[str, Any]], Awaitable[None]],
    stop_event: asyncio.Event,
    *,
    interval_s: float = 5.0,
) -> None:
    """Continuously replay pending receipt effects until server shutdown."""
    while not stop_event.is_set():
        try:
            await drain_all_pending_runner_dispatch_effects(conversation_store, callback)
        except Exception:  # noqa: BLE001 - durable pending rows survive transient store errors
            _logger.warning("Runner dispatch effects maintenance cycle failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
        except TimeoutError:
            continue


class _ClaimInput(BaseModel):
    conversation_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    persisted_item_id: str
    execution_owner_id: str


class _TransitionInput(BaseModel):
    conversation_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    execution_owner_id: str
    phase: str
    result: dict[str, Any] | None = None


def create_runner_dispatch_receipts_router(
    conversation_store: ConversationStore,
    *,
    on_indeterminate_failure: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    allowed_tunnel_tokens: frozenset[str] | None = None,
) -> APIRouter:
    """Build runner-only receipt endpoints on a static route prefix."""
    router = APIRouter()

    def _authenticated_runner_id(request: Request) -> str:
        token = (request.headers.get(RUNNER_TUNNEL_TOKEN_HEADER) or "").strip()
        claimed_runner_id = (request.headers.get(RUNNER_ID_HEADER) or "").strip()
        if not token or not claimed_runner_id:
            raise HTTPException(status_code=401, detail="runner authentication required")
        if allowed_tunnel_tokens is not None:
            if token not in allowed_tunnel_tokens:
                raise HTTPException(status_code=403, detail="runner token is not authorized")
            return claimed_runner_id
        if token_bound_runner_id(token) != claimed_runner_id:
            raise HTTPException(status_code=403, detail="runner token does not match identity")
        return claimed_runner_id

    @router.post("/runner-dispatch-receipts/claim")
    async def claim(request: Request, body: _ClaimInput) -> dict[str, Any]:
        runner_id = _authenticated_runner_id(request)
        try:
            return await asyncio.to_thread(
                conversation_store.claim_runner_dispatch_receipt,
                body.conversation_id,
                idempotency_key=body.idempotency_key,
                runner_id=runner_id,
                persisted_item_id=body.persisted_item_id,
                execution_owner_id=body.execution_owner_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/runner-dispatch-receipts/transition")
    async def transition(request: Request, body: _TransitionInput) -> dict[str, Any]:
        runner_id = _authenticated_runner_id(request)
        expected_phases = ("queued",) if body.phase == "running" else ("running",)
        allow_takeover = (
            body.phase == "failed"
            and isinstance(body.result, dict)
            and body.result.get("failure_code") == _INDETERMINATE_FAILURE_CODE
        )
        receipt = await asyncio.to_thread(
            conversation_store.transition_runner_dispatch_receipt,
            body.conversation_id,
            idempotency_key=body.idempotency_key,
            runner_id=runner_id,
            execution_owner_id=body.execution_owner_id,
            expected_phases=expected_phases,
            phase=body.phase,
            result=body.result,
            allow_takeover=allow_takeover,
        )
        if receipt is None:
            raise HTTPException(status_code=409, detail="receipt transition lost its CAS")
        if (
            on_indeterminate_failure is not None
            and receipt.get("effects_status") == "pending"
            and isinstance(receipt.get("result"), dict)
            and receipt["result"].get("failure_code") == _INDETERMINATE_FAILURE_CODE
        ):
            receipt = await _apply_pending_effects(
                conversation_store,
                receipt,
                on_indeterminate_failure,
            )
        return receipt

    @router.get("/runner-dispatch-receipts")
    async def get_receipts(
        request: Request,
        conversation_id: str | None = Query(default=None),
        idempotency_key: str | None = Query(default=None),
        recoverable: bool = Query(default=False),
    ) -> dict[str, Any]:
        runner_id = _authenticated_runner_id(request)
        if conversation_id is not None and idempotency_key is not None:
            receipt = await asyncio.to_thread(
                conversation_store.get_runner_dispatch_receipt,
                conversation_id,
                idempotency_key=idempotency_key,
            )
            if receipt is None:
                raise HTTPException(status_code=404, detail="dispatch receipt not found")
            if receipt["runner_id"] != runner_id:
                raise HTTPException(status_code=403, detail="receipt belongs to another runner")
            return receipt
        if not recoverable:
            raise HTTPException(
                status_code=400,
                detail="provide conversation_id+idempotency_key or recoverable=true",
            )
        receipts = await asyncio.to_thread(
            conversation_store.list_recoverable_runner_dispatch_receipts,
            runner_id,
        )
        recovered: list[dict[str, Any]] = []
        for receipt in receipts:
            request_body = await asyncio.to_thread(
                conversation_store.build_runner_dispatch_request,
                receipt["conversation_id"],
                persisted_item_id=receipt["persisted_item_id"],
                idempotency_key=receipt["idempotency_key"],
                runner_id=runner_id,
            )
            if request_body is not None:
                recovered.append({**receipt, "request": request_body})
        return {"data": recovered}

    return router
