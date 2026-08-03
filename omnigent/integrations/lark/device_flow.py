"""Feishu PersonalAgent registration device flow.

The Feishu registration API returns a short-lived session and QR verification
URL.  This module is deliberately transport-focused: persistence and HTTP
route policy live above it, while the only secret-bearing values remain in the
small success window between polling and credential encryption.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

_logger = logging.getLogger(__name__)

_APPLICATIONS_PATH = "/open-apis/application/v6/applications"
_TENANT_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_BOT_INFO_PATH = "/open-apis/bot/v3/info"

Json = Mapping[str, Any]
Request = Callable[[str, str, Json | None, Mapping[str, str] | None], Awaitable[Json]]


class FeishuDeviceFlowError(RuntimeError):
    """An actionable Feishu registration failure.

    ``kind`` is intentionally safe to return to a setup UI.  It never embeds
    request payloads, which could contain the freshly issued app secret.
    """

    def __init__(self, kind: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@dataclass(frozen=True)
class FeishuDeviceSession:
    """Non-secret information needed to render and poll a QR registration."""

    session: str
    verification_uri_complete: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class FeishuRegistration:
    """A successful registration result.  Keep this object out of logs."""

    app_id: str
    app_secret: str
    installer_open_id: str
    bot: Json


def _data(payload: Json) -> Json:
    value = payload.get("data", payload)
    return value if isinstance(value, Mapping) else {}


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


class FeishuPersonalAgentDeviceFlow:
    """Client for Feishu's PersonalAgent QR registration protocol.

    :param request: Optional HTTP seam used by tests.  It receives method,
        absolute URL, JSON body, and headers and returns a decoded JSON object.
    :param api_base_url: Feishu Open Platform origin.
    """

    def __init__(
        self,
        *,
        request: Request | None = None,
        api_base_url: str = "https://open.feishu.cn",
    ) -> None:
        self._base_url = api_base_url.rstrip("/")
        self._request = request or self._http_request

    async def _http_request(
        self,
        method: str,
        url: str,
        json: Json | None,
        headers: Mapping[str, str] | None,
    ) -> Json:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(method, url, json=json, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise FeishuDeviceFlowError(
                "network", "Feishu did not respond in time", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise FeishuDeviceFlowError(
                "network", "Could not reach Feishu", retryable=True
            ) from exc
        except ValueError as exc:
            raise FeishuDeviceFlowError("protocol", "Feishu returned an invalid response") from exc
        if not isinstance(payload, Mapping):
            raise FeishuDeviceFlowError("protocol", "Feishu returned an invalid response")
        return payload

    async def begin(self) -> FeishuDeviceSession:
        """Start a PersonalAgent registration and return its QR session."""
        payload = await self._call(
            "POST",
            _APPLICATIONS_PATH,
            {
                "action": "begin",
                "archetype": "PersonalAgent",
                "auth_method": "client_secret",
                "request_user_info": "open_id",
            },
        )
        data = _data(payload)
        session = _string(data.get("session"))
        verification_uri_complete = _string(data.get("verification_uri_complete"))
        interval = data.get("interval")
        expires_in = data.get("expires_in")
        if (
            session is None
            or verification_uri_complete is None
            or not isinstance(interval, int)
            or interval <= 0
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise FeishuDeviceFlowError(
                "protocol", "Feishu returned an incomplete registration session"
            )
        return FeishuDeviceSession(session, verification_uri_complete, interval, expires_in)

    async def poll(self, session: str) -> FeishuRegistration | None:
        """Poll a session, returning ``None`` while Feishu still awaits QR approval.

        Expired and denied sessions are terminal errors.  A successful result
        is enriched with Bot Info before returning, so callers persist one
        coherent installation record.
        """
        payload = await self._call("GET", f"{_APPLICATIONS_PATH}/{session}", None)
        data = _data(payload)
        state = (_string(data.get("status")) or _string(data.get("state")) or "").lower()
        if state in {"pending", "waiting", "processing"}:
            return None
        if state in {"denied", "rejected", "cancelled", "canceled"}:
            raise FeishuDeviceFlowError("denied", "Feishu registration was denied")
        if state in {"expired", "timeout", "timed_out"}:
            raise FeishuDeviceFlowError("expired", "Feishu registration session expired")
        if state not in {"success", "succeeded", "completed", "active"}:
            raise FeishuDeviceFlowError(
                "protocol", "Feishu returned an unknown registration state"
            )

        app_id = _string(data.get("app_id"))
        app_secret = _string(data.get("app_secret"))
        installer_open_id = _string(data.get("open_id"))
        if app_id is None or app_secret is None or installer_open_id is None:
            raise FeishuDeviceFlowError(
                "protocol", "Feishu completed registration without app credentials"
            )
        bot = await self.bot_info(app_id, app_secret)
        return FeishuRegistration(app_id, app_secret, installer_open_id, bot)

    async def bot_info(self, app_id: str, app_secret: str) -> Json:
        """Fetch Bot Info using the newly issued app credential."""
        token_payload = await self._call(
            "POST", _TENANT_TOKEN_PATH, {"app_id": app_id, "app_secret": app_secret}
        )
        token = _string(_data(token_payload).get("tenant_access_token"))
        if token is None:
            raise FeishuDeviceFlowError("protocol", "Feishu did not issue a tenant access token")
        bot_response = await self._call(
            "GET",
            _BOT_INFO_PATH,
            None,
            headers={"Authorization": f"Bearer {token}"},
        )
        bot_data = bot_response.get("data")
        bot = bot_data.get("bot") if isinstance(bot_data, Mapping) else None
        if not isinstance(bot, Mapping) or _string(bot.get("open_id")) is None:
            raise FeishuDeviceFlowError("protocol", "Feishu returned invalid Bot Info")
        return bot

    async def _call(
        self,
        method: str,
        path: str,
        json: Json | None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Json:
        payload = await self._request(method, f"{self._base_url}{path}", json, headers)
        code = payload.get("code")
        if isinstance(code, int) and code != 0:
            # Feishu's human message is deliberately not relayed or logged:
            # provider messages may reflect request values.
            _logger.info("Feishu registration API returned code %s", code)
            raise FeishuDeviceFlowError("provider", "Feishu rejected the registration request")
        return payload
