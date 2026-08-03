"""Tests for Feishu's PersonalAgent QR registration protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from omnigent.integrations.lark.device_flow import (
    FeishuDeviceFlowError,
    FeishuPending,
    FeishuPersonalAgentDeviceFlow,
)


class FakeFeishu:
    def __init__(self, replies: list[Mapping[str, Any]]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, str, Mapping[str, Any] | None, Mapping[str, str] | None]] = []

    async def __call__(
        self,
        method: str,
        url: str,
        json: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
    ) -> Mapping[str, Any]:
        self.calls.append((method, url, json, headers))
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_begin_uses_personal_agent_client_secret_contract() -> None:
    fake = FakeFeishu(
        [
            {
                "device_code": "device-code-1",
                "verification_uri_complete": "https://qr.example/session-1",
                "interval": 3,
                "expires_in": 180,
            }
        ]
    )
    flow = FeishuPersonalAgentDeviceFlow(request=fake)

    result = await flow.begin()

    assert result.session == "device-code-1"
    assert fake.calls == [
        (
            "POST",
            "https://accounts.feishu.cn/oauth/v1/app/registration",
            {
                "action": "begin",
                "archetype": "PersonalAgent",
                "auth_method": "client_secret",
                "request_user_info": "open_id",
            },
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
    ]


@pytest.mark.asyncio
async def test_begin_sends_form_data_instead_of_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def request(
        _client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        captured.update({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "device_code": "device-code-1",
                "verification_uri_complete": "https://qr.example/session-1",
                "interval": 5,
                "expires_in": 3600,
            },
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", request)

    await FeishuPersonalAgentDeviceFlow().begin()

    assert captured["data"] == {
        "action": "begin",
        "archetype": "PersonalAgent",
        "auth_method": "client_secret",
        "request_user_info": "open_id",
    }
    assert "json" not in captured


@pytest.mark.asyncio
async def test_http_rejection_is_a_provider_error_not_a_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def request(
        _client: httpx.AsyncClient, method: str, url: str, **_kwargs: Any
    ) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "invalid_request"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", request)

    with pytest.raises(FeishuDeviceFlowError) as exc_info:
        await FeishuPersonalAgentDeviceFlow().begin()

    assert exc_info.value.kind == "provider"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["authorization_pending", "slow_down"])
async def test_http_400_pending_errors_reach_poll_state_machine(
    monkeypatch: pytest.MonkeyPatch,
    error: str,
) -> None:
    async def request(
        _client: httpx.AsyncClient, method: str, url: str, **_kwargs: Any
    ) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": error},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", request)

    result = await FeishuPersonalAgentDeviceFlow().poll("device-code-1")

    assert isinstance(result, FeishuPending)
    assert result.interval == (10 if error == "slow_down" else 5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "kind"),
    [("access_denied", "denied"), ("expired_token", "expired")],
)
async def test_http_400_terminal_errors_reach_poll_state_machine(
    monkeypatch: pytest.MonkeyPatch,
    error: str,
    kind: str,
) -> None:
    async def request(
        _client: httpx.AsyncClient, method: str, url: str, **_kwargs: Any
    ) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": error},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", request)

    with pytest.raises(FeishuDeviceFlowError) as exc_info:
        await FeishuPersonalAgentDeviceFlow().poll("device-code-1")

    assert exc_info.value.kind == kind


@pytest.mark.asyncio
async def test_poll_success_fetches_bot_info_before_returning_secret() -> None:
    fake = FakeFeishu(
        [
            {
                "client_id": "cli_123",
                "client_secret": "top-secret",
                "user_info": {"open_id": "ou_installer"},
            },
            {"code": 0, "tenant_access_token": "tenant-token"},
            {"code": 0, "data": {"bot": {"open_id": "ou_bot", "app_name": "Agent"}}},
        ]
    )
    flow = FeishuPersonalAgentDeviceFlow(request=fake)

    result = await flow.poll("device-code-1")

    assert result is not None
    assert result.app_id == "cli_123"
    assert result.installer_open_id == "ou_installer"
    assert result.bot == {"open_id": "ou_bot", "app_name": "Agent"}
    assert fake.calls[0] == (
        "POST",
        "https://accounts.feishu.cn/oauth/v1/app/registration",
        {"action": "poll", "device_code": "device-code-1"},
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert fake.calls[1] == (
        "POST",
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": "cli_123", "app_secret": "top-secret"},
        None,
    )
    assert fake.calls[2][3] == {"Authorization": "Bearer tenant-token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "kind"),
    [("access_denied", "denied"), ("expired_token", "expired")],
)
async def test_poll_reports_terminal_session_diagnostics(state: str, kind: str) -> None:
    flow = FeishuPersonalAgentDeviceFlow(request=FakeFeishu([{"error": state}]))

    with pytest.raises(FeishuDeviceFlowError, match=kind) as exc_info:
        await flow.poll("session-1")

    assert exc_info.value.kind == kind


@pytest.mark.asyncio
async def test_slow_down_increases_subsequent_poll_interval() -> None:
    flow = FeishuPersonalAgentDeviceFlow(
        request=FakeFeishu(
            [
                {"error": "slow_down"},
                {"error": "authorization_pending"},
            ]
        )
    )

    slowed = await flow.poll("device-code-1")
    pending = await flow.poll("device-code-1")

    assert isinstance(slowed, FeishuPending)
    assert isinstance(pending, FeishuPending)
    assert slowed.interval == 10
    assert pending.interval == 10


@pytest.mark.asyncio
async def test_poll_rejects_a_response_without_credentials_or_status() -> None:
    flow = FeishuPersonalAgentDeviceFlow(request=FakeFeishu([{}]))

    with pytest.raises(FeishuDeviceFlowError, match="incomplete registration") as exc_info:
        await flow.poll("session-1")

    assert exc_info.value.kind == "protocol"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bot_reply",
    [
        {"code": 0},
        {"code": 0, "data": {"bot": {}}},
    ],
)
async def test_bot_info_requires_an_explicit_bot_with_open_id(
    bot_reply: Mapping[str, Any],
) -> None:
    flow = FeishuPersonalAgentDeviceFlow(
        request=FakeFeishu(
            [
                {"code": 0, "tenant_access_token": "tenant-token"},
                bot_reply,
            ]
        )
    )

    with pytest.raises(FeishuDeviceFlowError, match="Bot Info") as exc_info:
        await flow.bot_info("cli_123", "top-secret")

    assert exc_info.value.kind == "protocol"


@pytest.mark.asyncio
async def test_provider_error_is_safe_and_does_not_echo_secret() -> None:
    flow = FeishuPersonalAgentDeviceFlow(
        request=FakeFeishu([{"error": "invalid_request", "error_description": "sensitive"}])
    )

    with pytest.raises(FeishuDeviceFlowError) as exc_info:
        await flow.begin()

    assert "sensitive" not in str(exc_info.value)
    assert exc_info.value.kind == "provider"
