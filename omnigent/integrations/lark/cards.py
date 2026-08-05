"""Fixed Feishu card and menu payloads for the Omnigent team workspace."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping

JsonObject = dict[str, object]
NonceFactory = Callable[[str], str]

TOP_ENTRIES: tuple[tuple[str, str], ...] = (
    ("team_work", "团队工作"),
    ("all_sessions", "全部会话"),
    ("code_changes", "代码变更"),
    ("settings", "设置"),
)

QUICK_COMMANDS: tuple[tuple[str, str], ...] = (
    ("create_run", "新建任务"),
    ("current_run", "当前任务"),
    ("workers", "查看 Worker"),
    ("failures", "查看失败"),
    ("switch_workspace", "切换工作区"),
    ("deliverables", "查看成品"),
    ("help", "帮助"),
)

WORKSPACE_ACTIONS = TOP_ENTRIES + QUICK_COMMANDS

CONTEXT_SELECTORS: tuple[tuple[str, str], ...] = (
    ("workspace", "工作区"),
    ("repository", "仓库/服务"),
    ("host", "本地 Host"),
    ("execution_mode", "执行模式"),
)


def sign_action_payload(payload: Mapping[str, object], secret: str) -> str:
    """Sign the immutable server-owned fields carried by a card action."""
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest()


def action_value(
    action_id: str,
    *,
    signing_secret: str,
    nonce: str,
    run_id: str | None = None,
    task_id: str | None = None,
    attempt_id: str | None = None,
) -> JsonObject:
    """Build a signed action value without accepting arbitrary client fields."""
    payload: JsonObject = {
        "action_id": action_id,
        "run_id": run_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "nonce": nonce,
    }
    return {**payload, "signature": sign_action_payload(payload, signing_secret)}


def build_workspace_menu() -> JsonObject:
    """Return the fixed menu contract shared by every Omnigent team bot."""
    return {
        "top_entries": [{"action": action, "label": label} for action, label in TOP_ENTRIES],
        "quick_commands": [{"action": action, "label": label} for action, label in QUICK_COMMANDS],
        "context_selectors": [
            {"selector": selector, "label": label} for selector, label in CONTEXT_SELECTORS
        ],
    }


def build_workspace_card(
    *,
    signing_secret: str,
    nonce_factory: NonceFactory | None = None,
) -> JsonObject:
    """Build the persistent fallback card with the same fixed workspace actions."""
    make_nonce = nonce_factory or (lambda _action: secrets.token_urlsafe(18))
    buttons = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": "default",
            "value": action_value(
                action,
                signing_secret=signing_secret,
                nonce=make_nonce(action),
            ),
        }
        for action, label in WORKSPACE_ACTIONS
    ]
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "Omnigent 工作台"},
        },
        "elements": [
            {"tag": "action", "actions": buttons[:4]},
            {"tag": "action", "actions": buttons[4:8]},
            {"tag": "action", "actions": buttons[8:]},
        ],
    }


__all__ = [
    "CONTEXT_SELECTORS",
    "QUICK_COMMANDS",
    "TOP_ENTRIES",
    "WORKSPACE_ACTIONS",
    "action_value",
    "build_workspace_card",
    "build_workspace_menu",
    "sign_action_payload",
]
