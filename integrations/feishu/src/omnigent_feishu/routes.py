"""Standalone Agent-scoped installation, binding, surface, and webhook routes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from omnigent_feishu.adapter import FeishuAdapter
from omnigent_feishu.credentials import FeishuCredentialCipher
from omnigent_feishu.device_flow import (
    FeishuDeviceFlowError,
    FeishuPending,
    FeishuPersonalAgentDeviceFlow,
)
from omnigent_feishu.protocol import FeishuProtocolError
from omnigent_feishu.router import FeishuRoutingError
from omnigent_feishu.store import FeishuStore
from omnigent_feishu.surface import BotSurfaceProvisioner


class BindingRequest(BaseModel):
    installation_id: str
    chat_id: str
    thread_id: str | None = None
    workspace_id: str | None = None
    host_id: str | None = None
    execution_mode: str = "auto"
    allowed_members: list[str] = Field(default_factory=list)


def _installation(value: Any) -> dict[str, object]:
    data = asdict(value)
    data.pop("app_secret_ciphertext", None)
    data["object"] = "feishu.installation"
    return data


def create_feishu_router(
    store: FeishuStore,
    device_flow: FeishuPersonalAgentDeviceFlow,
    cipher: FeishuCredentialCipher,
    adapter: FeishuAdapter,
    *,
    surface_provisioner: BotSurfaceProvisioner | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post(
        "/v1/agents/{agent_id}/feishu/installations",
        status_code=201,
    )
    async def begin_install(agent_id: str) -> dict[str, object]:
        try:
            session = await device_flow.begin()
            installation = await store.create_pending_installation(
                agent_id=agent_id,
                session=session.session,
                verification_uri=session.verification_uri_complete,
            )
        except FeishuDeviceFlowError as exc:
            raise HTTPException(502, {"code": exc.kind, "retryable": exc.retryable}) from None
        return {
            **_installation(installation),
            "session": session.session,
            "verification_uri_complete": session.verification_uri_complete,
            "interval": session.interval,
            "expires_in": session.expires_in,
        }

    @router.get("/v1/agents/{agent_id}/feishu/installations/{session}")
    async def poll_install(agent_id: str, session: str) -> dict[str, object]:
        installation = await store.get_installation_by_session(session)
        if installation is None or installation.agent_id != agent_id:
            raise HTTPException(404, {"code": "not_found"})
        if installation.status == "connected":
            return _installation(installation)
        try:
            result = await device_flow.poll(session)
            if isinstance(result, FeishuPending):
                return {
                    **_installation(installation),
                    "interval": result.interval,
                    "verification_uri_complete": installation.verification_uri,
                }
            bot_open_id = str(result.bot["open_id"])
            installation = await store.connect_installation(
                installation.id,
                app_id=result.app_id,
                app_secret_ciphertext=cipher.encrypt(result.app_secret),
                installer_open_id=result.installer_open_id,
                bot_open_id=bot_open_id,
            )
            surface = None
            if surface_provisioner is not None:
                surface = (
                    await surface_provisioner.ensure(installation.id, agent_id=agent_id)
                ).to_dict()
            return {**_installation(installation), "surface": surface}
        except FeishuDeviceFlowError as exc:
            await store.mark_installation_error(installation.id, exc.kind)
            raise HTTPException(502, {"code": exc.kind, "retryable": exc.retryable}) from None

    @router.get("/v1/agents/{agent_id}/feishu")
    async def installation_status(agent_id: str) -> dict[str, object]:
        installation = await store.get_agent_installation(agent_id)
        if installation is None:
            raise HTTPException(404, {"code": "not_found"})
        return _installation(installation)

    @router.delete("/v1/agents/{agent_id}/feishu", status_code=204)
    async def delete_installation(agent_id: str) -> Response:
        if not await store.delete_agent_installation(agent_id):
            raise HTTPException(404, {"code": "not_found"})
        return Response(status_code=204)

    @router.put("/v1/agents/{agent_id}/feishu/binding")
    async def bind(agent_id: str, body: BindingRequest) -> dict[str, object]:
        installation = await store.get_installation(body.installation_id)
        if installation is None or installation.agent_id != agent_id:
            raise HTTPException(404, {"code": "not_found"})
        binding = await store.bind_thread(
            installation_id=body.installation_id,
            chat_id=body.chat_id,
            thread_id=body.thread_id,
            agent_id=agent_id,
            workspace_id=body.workspace_id,
            host_id=body.host_id,
            execution_mode=body.execution_mode,
            allowed_members=body.allowed_members,
        )
        return asdict(binding)

    @router.get("/v1/agents/{agent_id}/feishu/surface/status")
    async def surface_status(agent_id: str) -> dict[str, object]:
        installation = await store.get_agent_installation(agent_id)
        if installation is None:
            raise HTTPException(404, {"code": "not_found"})
        surface = await store.get_surface(installation.id)
        if surface is None:
            return {"status": "pending", "installation_id": installation.id}
        return dict(surface)

    @router.post("/v1/agents/{agent_id}/feishu/surface/reinitialize")
    async def reinitialize_surface(agent_id: str) -> dict[str, object]:
        installation = await store.get_agent_installation(agent_id)
        if installation is None:
            raise HTTPException(404, {"code": "not_found"})
        if surface_provisioner is None:
            raise HTTPException(503, {"code": "surface_unavailable"})
        return (await surface_provisioner.ensure(installation.id, agent_id=agent_id)).to_dict()

    @router.post("/v1/feishu/webhook")
    @router.post("/v1/feishu/action")
    async def webhook(request: Request) -> dict[str, object]:
        raw = await request.body()
        installation_id = request.headers.get("x-omnigent-feishu-installation")
        if not installation_id:
            try:
                payload = json.loads(raw)
            except (UnicodeError, ValueError):
                payload = {}
            header = payload.get("header", {}) if isinstance(payload, Mapping) else {}
            app_id = (header.get("app_id") if isinstance(header, Mapping) else None) or (
                payload.get("app_id") if isinstance(payload, Mapping) else None
            )
            installation = (
                await store.get_installation_by_app_id(app_id) if isinstance(app_id, str) else None
            )
            if installation is not None:
                installation_id = installation.id
            elif isinstance(payload, Mapping) and payload.get("challenge") is not None:
                installation_id = "challenge"
            else:
                raise HTTPException(400, {"code": "missing_installation"})
        try:
            result = await adapter.receive(
                raw,
                {key.lower(): value for key, value in request.headers.items()},
                installation_id=installation_id,
            )
        except FeishuProtocolError:
            raise HTTPException(401, {"code": "invalid_webhook"}) from None
        except FeishuRoutingError as exc:
            status = 403 if exc.code == "forbidden" else 400
            raise HTTPException(status, {"code": exc.code}) from None
        response = result.response
        if not isinstance(response, dict):
            response = {"result": response}
        return {**response, "duplicate": result.duplicate}

    return router


__all__ = ["BindingRequest", "create_feishu_router"]
