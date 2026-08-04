"""Deprecated embedded Feishu routes retained as an explicit 410 wrapper."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

_RETIRED_DETAIL = {
    "code": "embedded_feishu_retired",
    "message": "Embedded Feishu routes have moved to the standalone integration",
}


def create_feishu_router(*_args: Any, **_kwargs: Any) -> APIRouter:
    """Return compatibility routes that cannot execute embedded provider code."""
    router = APIRouter()

    @router.post("/feishu/installations")
    @router.get("/feishu/installations/{session}")
    @router.post("/feishu/installations/{installation_id}/surface/reinitialize")
    @router.get("/feishu/installations/{installation_id}/surface/status")
    @router.post("/teams/{team_id}/feishu/install/begin")
    @router.get("/teams/{team_id}/feishu/install/{session}/status")
    @router.post("/teams/{team_id}/feishu/webhook")
    @router.post("/feishu/webhook")
    async def embedded_feishu_retired() -> None:
        raise HTTPException(status_code=410, detail=_RETIRED_DETAIL)

    return router


__all__ = ["create_feishu_router"]
