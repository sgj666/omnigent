"""Feishu PersonalAgent installation route contracts.

The router intentionally has no database dependency.  Deployment wiring owns
the workspace/account scoping and supplies ``save_installation``; this module
owns the security-sensitive handoff from Feishu's one-time app secret to
authenticated ciphertext.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request

from omnigent.integrations.lark.credentials import (
    FeishuCredentialCipher,
    FeishuInstallationCredential,
)
from omnigent.integrations.lark.device_flow import (
    FeishuDeviceFlowError,
    FeishuPending,
    FeishuPersonalAgentDeviceFlow,
)
from omnigent.integrations.lark.surface import SurfaceResult

_logger = logging.getLogger(__name__)


class FeishuInstallationSaver(Protocol):
    """Persist a completed installation with ciphertext-only credentials."""

    def __call__(
        self,
        credential: FeishuInstallationCredential,
        *,
        bot: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...


class FeishuSurfaceProvisioner(Protocol):
    """Provision and inspect the stable workspace for one installation."""

    def ensure(self, installation_id: str) -> SurfaceResult: ...

    def status(self, installation_id: str) -> SurfaceResult | None: ...


def _flow_error(error: FeishuDeviceFlowError) -> HTTPException:
    """Translate safe device-flow diagnostics to setup-facing HTTP errors."""
    status = {
        "denied": 403,
        "expired": 410,
        "network": 503,
        "provider": 502,
        "protocol": 502,
    }.get(error.kind, 502)
    headers = {"Retry-After": "5"} if error.retryable else None
    return HTTPException(status_code=status, detail=str(error), headers=headers)


def create_feishu_router(
    device_flow: FeishuPersonalAgentDeviceFlow,
    credential_cipher: FeishuCredentialCipher,
    save_installation: FeishuInstallationSaver,
    *,
    lark_adapter: Any | None = None,
    surface_provisioner: FeishuSurfaceProvisioner | None = None,
) -> APIRouter:
    """Build routes for a QR-based Feishu PersonalAgent installation.

    ``POST /feishu/installations`` begins the provider session.  Clients retain
    its opaque ``session`` and poll ``GET /feishu/installations/{session}`` at
    no less than Feishu's advertised interval.  The completed response never
    contains an app secret; the saver receives only encrypted ciphertext.
    """
    router = APIRouter()

    @router.post("/feishu/installations")
    async def begin_installation() -> dict[str, Any]:
        """Create one QR verification session for a PersonalAgent app."""
        try:
            session = await device_flow.begin()
        except FeishuDeviceFlowError as exc:
            raise _flow_error(exc) from exc
        return {
            "object": "feishu.installation_session",
            "session": session.session,
            "verification_uri_complete": session.verification_uri_complete,
            "interval": session.interval,
            "expires_in": session.expires_in,
            "status": "pending",
        }

    @router.get("/feishu/installations/{session}")
    async def poll_installation(session: str) -> dict[str, Any]:
        """Return pending status or securely persist a completed installation."""
        try:
            registration = await device_flow.poll(session)
        except FeishuDeviceFlowError as exc:
            raise _flow_error(exc) from exc
        if registration is None or isinstance(registration, FeishuPending):
            interval = registration.interval if isinstance(registration, FeishuPending) else None
            return {
                "object": "feishu.installation_session",
                "session": session,
                "status": "pending",
                **({"interval": interval} if interval is not None else {}),
            }

        credential = FeishuInstallationCredential(
            installation_id=session,
            app_id=registration.app_id,
            app_secret_ciphertext=credential_cipher.encrypt(registration.app_secret),
            installer_open_id=registration.installer_open_id,
        )
        # The saver is synchronous for the same reason as other SQLAlchemy
        # stores; run it off the event loop.  Do not log the credential object:
        # it includes ciphertext and future implementations may add metadata.
        persisted = await asyncio.to_thread(save_installation, credential, bot=registration.bot)
        _logger.info("Feishu PersonalAgent installation completed: app_id=%s", registration.app_id)
        response: dict[str, Any] = {
            "object": "feishu.installation",
            "id": session,
            "app_id": registration.app_id,
            "installer_open_id": registration.installer_open_id,
            "bot": dict(registration.bot),
            "status": "active",
        }
        if persisted:
            # Only permit non-secret identity metadata through the persistence
            # seam; a mistaken saver can never place ciphertext in the route
            # contract.
            response.update(
                {
                    key: value
                    for key, value in persisted.items()
                    if key in {"id", "tenant_key", "status"}
                }
            )
        if surface_provisioner is not None:
            installation_id = str(response["id"])
            surface = await asyncio.to_thread(surface_provisioner.ensure, installation_id)
            response["surface"] = surface.to_dict()
        return response

    @router.post("/feishu/installations/{installation_id}/surface/reinitialize")
    async def reinitialize_surface(installation_id: str) -> dict[str, object]:
        """Re-probe capabilities and upsert the installation's existing surface."""
        if surface_provisioner is None:
            raise HTTPException(
                status_code=503,
                detail="Feishu surface provisioner is not configured",
            )
        result = await asyncio.to_thread(surface_provisioner.ensure, installation_id)
        return result.to_dict()

    @router.get("/feishu/installations/{installation_id}/surface/status")
    async def surface_status(installation_id: str) -> dict[str, object]:
        """Return the persisted provisioning status without contacting Feishu."""
        if surface_provisioner is None:
            raise HTTPException(
                status_code=503,
                detail="Feishu surface provisioner is not configured",
            )
        result = await asyncio.to_thread(surface_provisioner.status, installation_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Feishu surface status not found")
        return result.to_dict()

    # Team Builder clients use a team-scoped install URL.  Keep the original
    # provider-neutral endpoints above for existing callers, while these
    # aliases make the documented ``/teams/{id}/feishu/install/*`` contract
    # reachable from the application router.  Installation persistence is
    # intentionally unchanged; the team id is routing context only.
    @router.post("/teams/{team_id}/feishu/install/begin")
    async def begin_team_installation(team_id: str) -> dict[str, Any]:
        del team_id
        return await begin_installation()

    @router.get("/teams/{team_id}/feishu/install/{session}/status")
    async def poll_team_installation(team_id: str, session: str) -> dict[str, Any]:
        del team_id
        return await poll_installation(session)

    async def _receive_inbound(
        payload: Mapping[str, Any], headers: Mapping[str, str] | None, raw: bytes | None
    ) -> dict[str, Any]:
        if lark_adapter is None:
            raise HTTPException(status_code=503, detail="Lark inbound adapter is not configured")
        result = lark_adapter.receive(payload, headers=headers, raw=raw)
        response: dict[str, Any] = {
            "object": "feishu.inbound",
            "status": "duplicate" if result.duplicate else "accepted",
            "duplicate": result.duplicate,
        }
        if result.diagnostic:
            response["diagnostic"] = result.diagnostic
        if result.result is not None:
            response["result"] = result.result
        return response

    @router.post("/teams/{team_id}/feishu/webhook")
    async def receive_team_webhook(
        team_id: str, request: Request
    ) -> dict[str, Any]:
        del team_id
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid Feishu webhook JSON") from exc
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Feishu webhook must be a JSON object")
        return await _receive_inbound(payload, request.headers, raw_body)

    # Provider callbacks that do not carry a team path can still be routed by
    # the adapter's chat/thread binding.  This is useful for Feishu's public
    # event URL and keeps deployment wiring to one endpoint.
    @router.post("/feishu/webhook")
    async def receive_webhook(request: Request) -> dict[str, Any]:
        return await receive_team_webhook("", request)

    return router
