from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from omnigent_feishu.cards import (
    PERSISTENT_ACTIONS,
    action_value,
    build_guide_card,
    build_workspace_card,
    verify_action_value,
)
from omnigent_feishu.credentials import FeishuCredentialCipher, FeishuCredentialError
from omnigent_feishu.device_flow import FeishuPending, FeishuPersonalAgentDeviceFlow
from omnigent_feishu.protocol import challenge_response, decode_message, verify_signature
from omnigent_feishu.realtime import (
    FeishuRealtimeRuntime,
    _format_progress,
    _latest_assistant_text,
)


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
        "new_session",
        "create_workspace",
        "create_task",
        "current_run",
        "run_logs",
        "stop_run",
        "help",
    }
    guide = build_guide_card(
        signing_secret="action-secret",
        agent_id="ag_1",
        workspace_id="/Users/test/project",
        nonce_factory=lambda action: f"guide-{action}",
    )
    guide_actions = [
        button
        for element in guide["elements"]
        if element.get("tag") == "action"
        for button in element["actions"]
    ]
    assert {button["value"]["action_id"] for button in guide_actions} == {
        "new_session",
        "create_task",
        "switch_workspace",
        "create_workspace",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bot_response",
    [
        {"code": 0, "msg": "success", "bot": {"open_id": "ou_bot"}},
        {"data": {"bot": {"open_id": "ou_bot"}}},
    ],
)
async def test_device_flow_accepts_supported_bot_info_shapes(bot_response) -> None:
    replies = [
        {"tenant_access_token": "tenant-token"},
        bot_response,
    ]

    async def request(_method, _url, _body, _headers):
        return replies.pop(0)

    flow = FeishuPersonalAgentDeviceFlow(request=request)

    assert await flow.bot_info("app-id", "app-secret") == {"open_id": "ou_bot"}


def test_realtime_runtime_exposes_reply_and_reaction_transports() -> None:
    assert callable(FeishuRealtimeRuntime._send_text)
    assert callable(FeishuRealtimeRuntime._add_reaction)
    assert callable(FeishuRealtimeRuntime._delete_reaction)
    assert (
        _latest_assistant_text(
            {
                "data": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ]
            }
        )
        == "done"
    )


def test_progress_card_keeps_each_distinct_interim_reply() -> None:
    card = _format_progress(
        ["已派发给两位搭档", "Claude 回来了，GPT 还在想"], final=False, waiting=True
    )
    assert "**第 1 次回应**" in card
    assert "**第 2 次回应**" in card
    assert "⏳ _正在等待协作者完成…_" in card
    assert "任务过程" not in card
    assert "**本轮完成" in _format_progress(["已派发给两位搭档", "最终结论"], final=True)


@pytest.mark.asyncio
async def test_realtime_retries_after_a_card_patch_failure() -> None:
    runtime = FeishuRealtimeRuntime(None, None, None, None)  # type: ignore[arg-type]
    runtime._patch_card = AsyncMock(side_effect=RuntimeError("temporary Feishu failure"))

    delivered = await runtime._patch_card_safely(
        "app", "secret", "message", "正在回复", "progress", event_id="event", run_id="run"
    )

    assert delivered is False


@pytest.mark.asyncio
async def test_realtime_card_action_routes_and_replies_with_a_guide_card() -> None:
    runtime = FeishuRealtimeRuntime(None, None, None, None)  # type: ignore[arg-type]
    guide_card = {"schema": "2.0", "header": {"title": {"content": "开始工作"}}}
    runtime._adapter = SimpleNamespace(  # type: ignore[assignment]
        receive=AsyncMock(
            return_value=SimpleNamespace(
                response={"run": {"guide_card": guide_card, "message": "已新建会话"}}
            )
        )
    )
    runtime._send_interactive_card = AsyncMock()
    runtime._send_text = AsyncMock()
    installation = SimpleNamespace(id="install-1", app_id="app-id")
    event = SimpleNamespace(
        header=SimpleNamespace(event_id="evt-action"),
        event=SimpleNamespace(
            action=SimpleNamespace(value={"action_id": "new_session", "nonce": "nonce"}),
            operator=SimpleNamespace(open_id="ou-user"),
            context=SimpleNamespace(open_chat_id="oc_chat"),
        ),
    )

    await runtime._receive_action(installation, "secret", event)

    raw = runtime._adapter.receive.await_args.args[0]
    payload = json.loads(raw)
    assert payload["event"]["operator"] == {"open_id": "ou-user"}
    assert payload["event"]["context"] == {"open_chat_id": "oc_chat"}
    runtime._send_interactive_card.assert_awaited_once_with(
        "app-id", "secret", "oc_chat", "chat_id", guide_card
    )
    runtime._send_text.assert_awaited_once_with("app-id", "secret", "oc_chat", "已新建会话")
