from __future__ import annotations

import hashlib
import logging

import pytest
from omnigent_feishu.cards import (
    PERSISTENT_ACTIONS,
    action_value,
    build_workspace_card,
    verify_action_value,
)
from omnigent_feishu.credentials import FeishuCredentialCipher, FeishuCredentialError
from omnigent_feishu.device_flow import (
    FeishuDeviceFlowError,
    FeishuPending,
    FeishuPersonalAgentDeviceFlow,
)
from omnigent_feishu.protocol import challenge_response, decode_message, verify_signature


def test_protocol_challenge_message_and_signature() -> None:
    assert challenge_response({"challenge": "c", "token": "v"}, "v") == {"challenge": "c"}
    payload = {
        "header": {"event_id": "evt"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_sender"}},
            "message": {"chat_id": "chat", "content": '{"text":"do it"}'},
        },
    }
    assert decode_message(payload).text == "do it"
    body = b"body"
    expected = hashlib.sha256(b"1" + b"n" + b"s" + body).hexdigest()
    assert verify_signature(timestamp="1", nonce="n", body=body, secret="s", signature=expected)


def test_credentials_and_cards_are_secret_safe() -> None:
    cipher = FeishuCredentialCipher("operator-secret-key-material")
    encrypted = cipher.encrypt("app-secret")
    assert "app-secret" not in encrypted
    assert cipher.decrypt(encrypted) == "app-secret"
    with pytest.raises(FeishuCredentialError):
        cipher.decrypt(encrypted[:-2] + "xx")
    value = action_value(
        "create_run", signing_secret="action-secret", nonce="nonce", agent_id="ag_1"
    )
    assert verify_action_value(value, "action-secret")
    card = build_workspace_card(
        signing_secret="action-secret", nonce_factory=lambda action: f"n-{action}"
    )
    buttons = card["elements"][0]["actions"]
    assert len(buttons) == len(PERSISTENT_ACTIONS)
    assert {button["value"]["action_id"] for button in buttons} >= {
        "switch_workspace",
        "create_run",
        "current_run",
        "run_logs",
        "stop_run",
        "help",
    }


@pytest.mark.asyncio
async def test_device_flow_uses_form_contract_and_preserves_pending() -> None:
    calls = []
    replies = [
        {
            "device_code": "device",
            "verification_uri_complete": "https://qr",
            "interval": 3,
            "expires_in": 120,
        },
        {"error": "authorization_pending"},
    ]

    async def request(method, url, body, headers):
        calls.append((method, url, body, headers))
        return replies.pop(0)

    flow = FeishuPersonalAgentDeviceFlow(request=request)
    session = await flow.begin()
    pending = await flow.poll(session.session)
    assert isinstance(pending, FeishuPending)
    assert calls[0][1] == "https://accounts.feishu.cn/oauth/v1/app/registration"
    assert calls[0][3] == {"Content-Type": "application/x-www-form-urlencoded"}


def _flow_returning(bot_response: object) -> FeishuPersonalAgentDeviceFlow:
    replies: list[object] = [{"tenant_access_token": "tenant-token"}, bot_response]

    async def request(_method, _url, _body, _headers):
        return replies.pop(0)

    return FeishuPersonalAgentDeviceFlow(request=request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bot_response",
    [
        pytest.param({"code": 0, "msg": "success", "bot": {"open_id": "ou_bot"}}, id="top-level"),
        pytest.param({"data": {"bot": {"open_id": "ou_bot"}}}, id="nested-data"),
    ],
)
async def test_device_flow_accepts_supported_bot_info_shapes(bot_response) -> None:
    flow = _flow_returning(bot_response)
    assert await flow.bot_info("app-id", "app-secret") == {"open_id": "ou_bot"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bot_response",
    [
        pytest.param({"code": 0, "msg": "success"}, id="no-envelope"),
        pytest.param({"data": {"code": 0}}, id="data-without-bot"),
        pytest.param({"data": {"bot": {}}}, id="bot-without-open-id"),
        pytest.param({"data": {"bot": {"open_id": "   "}}}, id="blank-open-id"),
        pytest.param({"bot": "ou_bot"}, id="bot-not-a-mapping"),
        pytest.param({"data": "unexpected", "bot": None}, id="data-not-a-mapping"),
    ],
)
async def test_device_flow_rejects_unusable_bot_info(bot_response) -> None:
    flow = _flow_returning(bot_response)
    with pytest.raises(FeishuDeviceFlowError) as excinfo:
        await flow.bot_info("app-id", "app-secret")
    assert excinfo.value.kind == "protocol"


@pytest.mark.asyncio
async def test_device_flow_bot_info_failure_log_omits_secrets(caplog) -> None:
    flow = _flow_returning({"code": 99, "msg": "permission denied"})
    with caplog.at_level(logging.WARNING), pytest.raises(FeishuDeviceFlowError):
        await flow.bot_info("app-id", "app-secret")
    logged = caplog.text
    assert "app-id" in logged
    assert "app-secret" not in logged
    assert "tenant-token" not in logged
