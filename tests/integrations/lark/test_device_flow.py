"""Tests for Feishu's PersonalAgent QR registration protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from omnigent.integrations.lark.device_flow import (
    FeishuDeviceFlowError,
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
                "code": 0,
                "data": {
                    "session": "session-1",
                    "verification_uri_complete": "https://qr.example/session-1",
                    "interval": 3,
                    "expires_in": 180,
                },
            }
        ]
    )
    flow = FeishuPersonalAgentDeviceFlow(request=fake, api_base_url="https://feishu.test")

    result = await flow.begin()

    assert result.session == "session-1"
    assert fake.calls == [
        (
            "POST",
            "https://feishu.test/open-apis/application/v6/applications",
            {
                "action": "begin",
                "archetype": "PersonalAgent",
                "auth_method": "client_secret",
                "request_user_info": "open_id",
            },
            None,
        )
    ]


@pytest.mark.asyncio
async def test_poll_success_fetches_bot_info_before_returning_secret() -> None:
    fake = FakeFeishu(
        [
            {
                "code": 0,
                "data": {
                    "status": "success",
                    "app_id": "cli_123",
                    "app_secret": "top-secret",
                    "open_id": "ou_installer",
                },
            },
            {"code": 0, "tenant_access_token": "tenant-token"},
            {"code": 0, "data": {"bot": {"open_id": "ou_bot", "app_name": "Agent"}}},
        ]
    )
    flow = FeishuPersonalAgentDeviceFlow(request=fake, api_base_url="https://feishu.test")

    result = await flow.poll("session-1")

    assert result is not None
    assert result.app_id == "cli_123"
    assert result.installer_open_id == "ou_installer"
    assert result.bot == {"open_id": "ou_bot", "app_name": "Agent"}
    assert fake.calls[1] == (
        "POST",
        "https://feishu.test/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": "cli_123", "app_secret": "top-secret"},
        None,
    )
    assert fake.calls[2][3] == {"Authorization": "Bearer tenant-token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "kind"),
    [("denied", "denied"), ("expired", "expired")],
)
async def test_poll_reports_terminal_session_diagnostics(state: str, kind: str) -> None:
    flow = FeishuPersonalAgentDeviceFlow(
        request=FakeFeishu([{"code": 0, "data": {"status": state}}])
    )

    with pytest.raises(FeishuDeviceFlowError, match=kind) as exc_info:
        await flow.poll("session-1")

    assert exc_info.value.kind == kind


@pytest.mark.asyncio
async def test_poll_rejects_a_response_without_an_explicit_state() -> None:
    flow = FeishuPersonalAgentDeviceFlow(request=FakeFeishu([{"code": 0, "data": {}}]))

    with pytest.raises(FeishuDeviceFlowError, match="registration state") as exc_info:
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
        request=FakeFeishu([{"code": 999, "msg": "bad app_secret=sensitive"}])
    )

    with pytest.raises(FeishuDeviceFlowError) as exc_info:
        await flow.begin()

    assert "sensitive" not in str(exc_info.value)
    assert exc_info.value.kind == "provider"
