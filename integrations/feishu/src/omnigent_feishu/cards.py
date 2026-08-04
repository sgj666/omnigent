"""Fixed Agent/Workspace/Run Feishu cards and signed action values."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping

NonceFactory = Callable[[str], str]

PERSISTENT_ACTIONS: tuple[tuple[str, str], ...] = (
    ("switch_workspace", "切换工作区"),
    ("create_run", "创建任务"),
    ("current_run", "当前 Run"),
    ("list_runs", "任务列表/状态"),
    ("run_logs", "日志/失败原因"),
    ("stop_run", "停止 Run"),
    ("help", "帮助"),
)
APPROVAL_ACTIONS: tuple[tuple[str, str], ...] = (
    ("approve", "批准"),
    ("deny", "拒绝"),
)
ALLOWED_ACTIONS = frozenset(action for action, _ in PERSISTENT_ACTIONS + APPROVAL_ACTIONS)


def sign_action_payload(payload: Mapping[str, object], secret: str) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest()


def action_value(
    action_id: str,
    *,
    signing_secret: str,
    nonce: str,
    agent_id: str | None = None,
    workspace_id: str | None = None,
    run_id: str | None = None,
    approval_id: str | None = None,
) -> dict[str, object]:
    if action_id not in ALLOWED_ACTIONS:
        raise ValueError("action is not allowed")
    payload: dict[str, object] = {
        "action_id": action_id,
        "agent_id": agent_id,
        "workspace_id": workspace_id,
        "run_id": run_id,
        "approval_id": approval_id,
        "nonce": nonce,
    }
    return {**payload, "signature": sign_action_payload(payload, signing_secret)}


def verify_action_value(value: Mapping[str, object], secret: str) -> bool:
    signature = value.get("signature")
    action = value.get("action_id")
    if not isinstance(signature, str) or action not in ALLOWED_ACTIONS:
        return False
    payload = {key: item for key, item in value.items() if key != "signature"}
    return hmac.compare_digest(signature, sign_action_payload(payload, secret))


def build_workspace_menu() -> dict[str, object]:
    return {
        "profile": "omnigent-agent",
        "entries": [{"action": action, "label": label} for action, label in PERSISTENT_ACTIONS],
    }


def build_workspace_card(
    *,
    signing_secret: str,
    agent_id: str | None = None,
    workspace_id: str | None = None,
    nonce_factory: NonceFactory | None = None,
) -> dict[str, object]:
    nonce = nonce_factory or (lambda _action: secrets.token_urlsafe(18))
    buttons = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "value": action_value(
                action,
                signing_secret=signing_secret,
                nonce=nonce(action),
                agent_id=agent_id,
                workspace_id=workspace_id,
            ),
        }
        for action, label in PERSISTENT_ACTIONS
    ]
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "Omnigent Agent"}},
        "elements": [{"tag": "action", "actions": buttons}],
    }


def build_run_card(
    run: Mapping[str, object], *, signing_secret: str, approval_required: bool = False
) -> dict[str, object]:
    run_id = str(run.get("id", ""))
    actions = [("current_run", "刷新"), ("run_logs", "日志"), ("stop_run", "停止")]
    if approval_required:
        actions.extend(APPROVAL_ACTIONS)
    return {
        "header": {"title": {"tag": "plain_text", "content": f"Run {run_id}"}},
        "elements": [
            {"tag": "markdown", "content": f"状态：{run.get('status', 'unknown')}"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label},
                        "value": action_value(
                            action,
                            signing_secret=signing_secret,
                            nonce=secrets.token_urlsafe(18),
                            run_id=run_id,
                            approval_id=str(run.get("approval_id"))
                            if run.get("approval_id")
                            else None,
                        ),
                    }
                    for action, label in actions
                ],
            },
        ],
    }


__all__ = [
    "ALLOWED_ACTIONS",
    "APPROVAL_ACTIONS",
    "PERSISTENT_ACTIONS",
    "action_value",
    "build_run_card",
    "build_workspace_card",
    "build_workspace_menu",
    "sign_action_payload",
    "verify_action_value",
]
