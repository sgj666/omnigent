"""Feishu PersonalAgent installation route contracts.

The router intentionally has no database dependency.  Deployment wiring owns
the workspace/account scoping and supplies ``save_installation``; this module
owns the security-sensitive handoff from Feishu's one-time app secret to
authenticated ciphertext.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException

from omnigent.integrations.lark.credentials import (
    FeishuCredentialCipher,
    FeishuInstallationCredential,
)
from omnigent.integrations.lark.device_flow import (
    FeishuDeviceFlowError,
    FeishuPersonalAgentDeviceFlow,
)

_logger = logging.getLogger(__name__)


class FeishuInstallationSaver(Protocol):
    """Persist a completed installation with ciphertext-only credentials."""

    def __call__(
        self,
        credential: FeishuInstallationCredential,
        *,
        bot: Mapping[str, Any],
    ) -> Mapping[str, Any] | None: ...


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
        if registration is None:
            return {
                "object": "feishu.installation_session",
                "session": session,
                "status": "pending",
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
        return response

    return router
