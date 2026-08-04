from __future__ import annotations

import hashlib

import pytest
from omnigent_feishu.cards import (
    PERSISTENT_ACTIONS,
    action_value,
    build_workspace_card,
    verify_action_value,
)
from omnigent_feishu.credentials import FeishuCredentialCipher, FeishuCredentialError
from omnigent_feishu.device_flow import FeishuPending, FeishuPersonalAgentDeviceFlow
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
