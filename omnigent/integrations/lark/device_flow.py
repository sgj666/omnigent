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
from typing import TypeAlias, cast

import httpx

_logger = logging.getLogger(__name__)

_REGISTRATION_BASE_URL = "https://accounts.feishu.cn"
_REGISTRATION_PATH = "/oauth/v1/app/registration"
_TENANT_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_BOT_INFO_PATH = "/open-apis/bot/v3/info"
_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
Request = Callable[[str, str, JsonObject | None, Mapping[str, str] | None], Awaitable[JsonObject]]


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
    bot: JsonObject


@dataclass(frozen=True)
class FeishuPending:
    """Non-terminal registration state and the next minimum poll interval."""

    interval: int


def _coerce_json(value: object) -> JsonValue:
    """Convert an untyped HTTP JSON response to the supported JSON shape."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_coerce_json(item) for item in value]
    if isinstance(value, dict):
        result: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise FeishuDeviceFlowError("protocol", "Feishu returned an invalid response")
            result[key] = _coerce_json(item)
        return result
    raise FeishuDeviceFlowError("protocol", "Feishu returned an invalid response")


def _data(payload: JsonObject) -> JsonObject:
    value = payload.get("data", payload)
    return value if isinstance(value, dict) else {}


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
        registration_base_url: str = _REGISTRATION_BASE_URL,
    ) -> None:
        self._base_url = api_base_url.rstrip("/")
        self._registration_base_url = registration_base_url.rstrip("/")
        self._request = request or self._http_request
        self._poll_intervals: dict[str, int] = {}

    async def _http_request(
        self,
        method: str,
        url: str,
        json: JsonObject | None,
        headers: Mapping[str, str] | None,
    ) -> JsonObject:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if headers and headers.get("Content-Type") == _FORM_HEADERS["Content-Type"]:
                    response = await client.request(method, url, data=json, headers=headers)
                else:
                    response = await client.request(method, url, json=json, headers=headers)
                payload = response.json()
                registration_error = (
                    url == f"{self._registration_base_url}{_REGISTRATION_PATH}"
                    and isinstance(payload, dict)
                    and _string(payload.get("error")) is not None
                )
                if response.is_error and not registration_error:
                    response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FeishuDeviceFlowError(
                "network", "Feishu did not respond in time", retryable=True
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise FeishuDeviceFlowError(
                "provider", "Feishu rejected the registration request"
            ) from exc
        except httpx.RequestError as exc:
            raise FeishuDeviceFlowError(
                "network", "Could not reach Feishu", retryable=True
            ) from exc
        except ValueError as exc:
            raise FeishuDeviceFlowError("protocol", "Feishu returned an invalid response") from exc
        payload = _coerce_json(cast(object, payload))
        if not isinstance(payload, dict):
            raise FeishuDeviceFlowError("protocol", "Feishu returned an invalid response")
        return payload

    async def begin(self) -> FeishuDeviceSession:
        """Start a PersonalAgent registration and return its QR session."""
        payload = await self._request(
            "POST",
            f"{self._registration_base_url}{_REGISTRATION_PATH}",
            {
                "action": "begin",
                "archetype": "PersonalAgent",
                "auth_method": "client_secret",
                "request_user_info": "open_id",
            },
            _FORM_HEADERS,
        )
        if _string(payload.get("error")) is not None:
            raise FeishuDeviceFlowError("provider", "Feishu rejected the registration request")
        session = _string(payload.get("device_code"))
        verification_uri_complete = _string(payload.get("verification_uri_complete"))
        interval = payload.get("interval")
        expires_in = payload.get("expires_in", payload.get("expire_in"))
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
        self._poll_intervals[session] = interval
        return FeishuDeviceSession(session, verification_uri_complete, interval, expires_in)

    async def poll(self, session: str) -> FeishuRegistration | FeishuPending:
        """Poll a session, returning its cadence while Feishu awaits approval.

        Expired and denied sessions are terminal errors.  A successful result
        is enriched with Bot Info before returning, so callers persist one
        coherent installation record.
        """
        payload = await self._request(
            "POST",
            f"{self._registration_base_url}{_REGISTRATION_PATH}",
            {"action": "poll", "device_code": session},
            _FORM_HEADERS,
        )
        error = (_string(payload.get("error")) or "").lower()
        interval = self._poll_intervals.get(session, 5)
        if error == "authorization_pending":
            return FeishuPending(interval)
        if error == "slow_down":
            interval += 5
            self._poll_intervals[session] = interval
            return FeishuPending(interval)
        if error == "access_denied":
            self._poll_intervals.pop(session, None)
            raise FeishuDeviceFlowError("denied", "Feishu registration was denied")
        if error == "expired_token":
            self._poll_intervals.pop(session, None)
            raise FeishuDeviceFlowError("expired", "Feishu registration session expired")
        if error:
            raise FeishuDeviceFlowError("provider", "Feishu rejected the registration request")

        app_id = _string(payload.get("client_id"))
        app_secret = _string(payload.get("client_secret"))
        user_info = payload.get("user_info")
        installer_open_id = (
            _string(user_info.get("open_id")) if isinstance(user_info, dict) else None
        )
        if app_id is None or app_secret is None or installer_open_id is None:
            raise FeishuDeviceFlowError(
                "protocol", "Feishu returned an incomplete registration result"
            )
        bot = await self.bot_info(app_id, app_secret)
        self._poll_intervals.pop(session, None)
        return FeishuRegistration(app_id, app_secret, installer_open_id, bot)

    async def bot_info(self, app_id: str, app_secret: str) -> JsonObject:
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
        bot = bot_data.get("bot") if isinstance(bot_data, dict) else None
        if not isinstance(bot, dict) or _string(bot.get("open_id")) is None:
            raise FeishuDeviceFlowError("protocol", "Feishu returned invalid Bot Info")
        return bot

    async def _call(
        self,
        method: str,
        path: str,
        json: JsonObject | None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        payload = await self._request(method, f"{self._base_url}{path}", json, headers)
        code = payload.get("code")
        if isinstance(code, int) and code != 0:
            # Feishu's human message is deliberately not relayed or logged:
            # provider messages may reflect request values.
            _logger.info("Feishu registration API returned code %s", code)
            raise FeishuDeviceFlowError("provider", "Feishu rejected the registration request")
        return payload
