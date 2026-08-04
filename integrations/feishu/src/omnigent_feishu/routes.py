"""Standalone Agent-scoped installation, binding, surface, and webhook routes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any
from urllib.parse import quote

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
from omnigent_feishu.surface import BotSurfaceProvisioner, enrich_surface


class BindingRequest(BaseModel):
    installation_id: str
    chat_id: str
    thread_id: str | None = None
    workspace_id: str | None = None
    host_id: str | None = None
    execution_mode: str = "auto"
    allowed_members: list[str] = Field(default_factory=list)


def _installation(value: Any, *, now: int) -> dict[str, object]:
    data = asdict(value)
    data.pop("app_secret_ciphertext", None)
    data["session"] = data.get("device_session")
    complete = data.get("verification_uri")
    base = data.pop("verification_uri_base", None)
    data["verification_uri"] = base or complete
    data["verification_uri_complete"] = complete
    data["qr_uri"] = complete
    expires_at = data.get("expires_at")
    if isinstance(expires_at, int):
        data["expires_in"] = max(0, expires_at - now)
    data["object"] = "feishu.installation"
    return data


def _opaque(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:16]
    return f"{kind}_{digest}"


def _binding(value: Any) -> dict[str, object]:
    data = asdict(value)
    data["chat_id"] = _opaque("chat", value.chat_id)
    data["thread_id"] = _opaque("thread", value.thread_id) if value.thread_id else None
    data["allowed_members"] = [_opaque("member", member) for member in value.allowed_members]
    data["allowed_member_count"] = len(value.allowed_members)
    if value.workspace_id is not None:
        workspace_id = quote(value.workspace_id, safe="")
        data["workspace"] = {
            "id": value.workspace_id,
            "href": f"/v1/workspaces/{workspace_id}",
            "repositories_href": f"/v1/workspaces/{workspace_id}/repositories",
        }
    else:
        data["workspace"] = None
    return data


def _safe_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bot_metadata(bot: Mapping[str, object]) -> dict[str, str | None]:
    tenant = bot.get("tenant")
    tenant_map = tenant if isinstance(tenant, Mapping) else {}
    avatar = bot.get("avatar")
    avatar_map = avatar if isinstance(avatar, Mapping) else {}
    return {
        "tenant_key": _safe_text(bot.get("tenant_key"))
        or _safe_text(tenant_map.get("tenant_key")),
        "tenant_name": _safe_text(bot.get("tenant_name")) or _safe_text(tenant_map.get("name")),
        "bot_name": _safe_text(bot.get("name")) or _safe_text(bot.get("app_name")),
        "bot_avatar_url": _safe_text(bot.get("avatar_url"))
        or _safe_text(avatar_map.get("avatar_origin"))
        or _safe_text(avatar_map.get("avatar_240")),
    }


def create_feishu_router(
    store: FeishuStore,
    device_flow: FeishuPersonalAgentDeviceFlow,
    cipher: FeishuCredentialCipher,
    adapter: FeishuAdapter,
    *,
    surface_provisioner: BotSurfaceProvisioner | None = None,
) -> APIRouter:
    router = APIRouter()

    async def installation_payload(installation: Any) -> dict[str, object]:
        payload = _installation(installation, now=store.now())
        binding = await store.get_agent_binding(installation.agent_id)
        payload["binding"] = (
            _binding(binding)
            if binding is not None and binding.installation_id == installation.id
            else None
        )
        surface = await store.get_surface(installation.id)
        payload["surface"] = enrich_surface(surface) if surface is not None else None
        return payload

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
                verification_uri_base=session.verification_uri,
                user_code=session.user_code,
                interval=session.interval,
                expires_in=session.expires_in,
            )
        except FeishuDeviceFlowError as exc:
            raise HTTPException(502, {"code": exc.kind, "retryable": exc.retryable}) from None
        return {
            **(await installation_payload(installation)),
        }

    @router.get("/v1/agents/{agent_id}/feishu/installations/{session}")
    async def poll_install(agent_id: str, session: str) -> dict[str, object]:
        installation = await store.get_installation_by_session(session)
        if installation is None or installation.agent_id != agent_id:
            raise HTTPException(404, {"code": "not_found"})
        if installation.status in {"connected", "expired"}:
            return await installation_payload(installation)
        try:
            restore = getattr(device_flow, "restore", None)
            if restore is not None and installation.interval is not None:
                restore(session, installation.interval)
            result = await device_flow.poll(session)
            if isinstance(result, FeishuPending):
                await store.update_pending_interval(installation.id, result.interval)
                refreshed = await store.get_installation(installation.id)
                assert refreshed is not None
                return await installation_payload(refreshed)
            bot_open_id = str(result.bot["open_id"])
            metadata = _bot_metadata(result.bot)
            metadata["tenant_key"] = result.tenant_key or metadata["tenant_key"]
            metadata["tenant_name"] = result.tenant_name or metadata["tenant_name"]
            installation = await store.connect_installation(
                installation.id,
                app_id=result.app_id,
                app_secret_ciphertext=cipher.encrypt(result.app_secret),
                installer_open_id=result.installer_open_id,
                bot_open_id=bot_open_id,
                **metadata,
            )
            surface = None
            if surface_provisioner is not None:
                surface = (
                    await surface_provisioner.ensure(installation.id, agent_id=agent_id)
                ).to_dict()
            payload = await installation_payload(installation)
            if surface is not None:
                payload["surface"] = surface
            return payload
        except FeishuDeviceFlowError as exc:
            await store.mark_installation_error(installation.id, exc.kind)
            if exc.kind == "expired":
                expired = await store.get_installation(installation.id)
                assert expired is not None
                return await installation_payload(expired)
            raise HTTPException(502, {"code": exc.kind, "retryable": exc.retryable}) from None

    @router.get("/v1/agents/{agent_id}/feishu")
    async def installation_status(agent_id: str) -> dict[str, object]:
        installation = await store.get_agent_installation(agent_id)
        if installation is None:
            raise HTTPException(404, {"code": "not_found"})
        return await installation_payload(installation)

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
        return _binding(binding)

    @router.get("/v1/agents/{agent_id}/feishu/surface/status")
    async def surface_status(agent_id: str) -> dict[str, object]:
        installation = await store.get_agent_installation(agent_id)
        if installation is None:
            raise HTTPException(404, {"code": "not_found"})
        surface = await store.get_surface(installation.id)
        if surface is None:
            return enrich_surface({"status": "pending", "installation_id": installation.id})
        return enrich_surface(surface)

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
