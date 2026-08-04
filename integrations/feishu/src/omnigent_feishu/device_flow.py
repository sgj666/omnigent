"""Feishu PersonalAgent QR registration flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

REGISTRATION_URL = "https://accounts.feishu.cn/oauth/v1/app/registration"
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
Request = Callable[
    [str, str, Mapping[str, Any] | None, Mapping[str, str] | None],
    Awaitable[Mapping[str, Any]],
]


class FeishuDeviceFlowError(RuntimeError):
    def __init__(self, kind: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@dataclass(frozen=True)
class FeishuDeviceSession:
    session: str
    verification_uri_complete: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class FeishuPending:
    interval: int


@dataclass(frozen=True, repr=False)
class FeishuRegistration:
    app_id: str
    app_secret: str
    installer_open_id: str
    bot: dict[str, Any]


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


class FeishuPersonalAgentDeviceFlow:
    """Transport-only registration client; callers encrypt returned secrets."""

    def __init__(
        self,
        *,
        request: Request | None = None,
        api_base_url: str = "https://open.feishu.cn",
        registration_url: str = REGISTRATION_URL,
    ) -> None:
        self._request = request or self._http_request
        self._api = api_base_url.rstrip("/")
        self._registration_url = registration_url
        self._intervals: dict[str, int] = {}

    async def _http_request(
        self,
        method: str,
        url: str,
        body: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
    ) -> Mapping[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                kwargs: dict[str, Any] = {"headers": headers}
                if headers == FORM_HEADERS:
                    kwargs["data"] = body
                else:
                    kwargs["json"] = body
                response = await client.request(method, url, **kwargs)
                payload = response.json()
                if response.is_error and not (
                    url == self._registration_url
                    and isinstance(payload, Mapping)
                    and payload.get("error")
                ):
                    response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FeishuDeviceFlowError("network", "Feishu timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            raise FeishuDeviceFlowError(
                "network", "Could not reach Feishu", retryable=True
            ) from exc
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise FeishuDeviceFlowError("provider", "Feishu rejected the request") from exc
        if not isinstance(payload, Mapping):
            raise FeishuDeviceFlowError("protocol", "Feishu returned invalid JSON")
        return payload

    async def begin(self) -> FeishuDeviceSession:
        payload = await self._request(
            "POST",
            self._registration_url,
            {
                "action": "begin",
                "archetype": "PersonalAgent",
                "auth_method": "client_secret",
                "request_user_info": "open_id",
            },
            FORM_HEADERS,
        )
        if payload.get("error"):
            raise FeishuDeviceFlowError("provider", "Feishu rejected registration")
        session = _text(payload.get("device_code"))
        uri = _text(payload.get("verification_uri_complete"))
        interval = payload.get("interval")
        expires = payload.get("expires_in", payload.get("expire_in"))
        if (
            session is None
            or uri is None
            or not isinstance(interval, int)
            or interval < 1
            or not isinstance(expires, int)
            or expires < 1
        ):
            raise FeishuDeviceFlowError("protocol", "Incomplete registration session")
        self._intervals[session] = interval
        return FeishuDeviceSession(session, uri, interval, expires)

    async def poll(self, session: str) -> FeishuRegistration | FeishuPending:
        payload = await self._request(
            "POST",
            self._registration_url,
            {"action": "poll", "device_code": session},
            FORM_HEADERS,
        )
        error = str(payload.get("error", "")).lower()
        interval = self._intervals.get(session, 5)
        if error == "authorization_pending":
            return FeishuPending(interval)
        if error == "slow_down":
            interval += 5
            self._intervals[session] = interval
            return FeishuPending(interval)
        if error in {"access_denied", "expired_token"}:
            self._intervals.pop(session, None)
            kind = "denied" if error == "access_denied" else "expired"
            raise FeishuDeviceFlowError(kind, f"Feishu registration {kind}")
        if error:
            raise FeishuDeviceFlowError("provider", "Feishu rejected registration")
        app_id = _text(payload.get("client_id"))
        secret = _text(payload.get("client_secret"))
        user = payload.get("user_info")
        installer = _text(user.get("open_id")) if isinstance(user, Mapping) else None
        if app_id is None or secret is None or installer is None:
            raise FeishuDeviceFlowError("protocol", "Incomplete registration result")
        bot = await self.bot_info(app_id, secret)
        self._intervals.pop(session, None)
        return FeishuRegistration(app_id, secret, installer, bot)

    async def bot_info(self, app_id: str, app_secret: str) -> dict[str, Any]:
        token_payload = await self._request(
            "POST",
            f"{self._api}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret},
            None,
        )
        data = token_payload.get("data", token_payload)
        token = _text(data.get("tenant_access_token")) if isinstance(data, Mapping) else None
        if token is None:
            raise FeishuDeviceFlowError("protocol", "Feishu did not issue a token")
        response = await self._request(
            "GET",
            f"{self._api}/open-apis/bot/v3/info",
            None,
            {"Authorization": f"Bearer {token}"},
        )
        data = response.get("data", {})
        bot = data.get("bot") if isinstance(data, Mapping) else None
        if not isinstance(bot, Mapping) or _text(bot.get("open_id")) is None:
            raise FeishuDeviceFlowError("protocol", "Feishu returned invalid bot info")
        return dict(bot)


__all__ = [
    "FeishuDeviceFlowError",
    "FeishuDeviceSession",
    "FeishuPending",
    "FeishuPersonalAgentDeviceFlow",
    "FeishuRegistration",
]
