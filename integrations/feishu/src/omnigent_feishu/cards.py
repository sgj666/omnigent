"""Fixed Agent/Workspace/Run Feishu cards and signed action values."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping

NonceFactory = Callable[[str], str]

PERSISTENT_ACTIONS: tuple[tuple[str, str], ...] = (
    ("quick_commands", "快捷指令"),
    ("manage_devices", "管理设备"),
    ("new_session", "新建会话"),
    ("switch_workspace", "切换工作区"),
    ("create_workspace", "添加工作目录"),
    ("create_task", "创建任务"),
    ("stop_session", "终止会话"),
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
# ``create_run`` is accepted for cards issued by older installations.
ALLOWED_ACTIONS = frozenset(
    [
        *(action for action, _ in PERSISTENT_ACTIONS + APPROVAL_ACTIONS),
        "create_run",
        "elicitation_choice",
    ]
)


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
    host_id: str | None = None,
    run_id: str | None = None,
    approval_id: str | None = None,
    elicitation_id: str | None = None,
    choice: str | None = None,
) -> dict[str, object]:
    if action_id not in ALLOWED_ACTIONS:
        raise ValueError("action is not allowed")
    payload: dict[str, object] = {
        "action_id": action_id,
        "agent_id": agent_id,
        "workspace_id": workspace_id,
        "host_id": host_id,
        "run_id": run_id,
        "approval_id": approval_id,
        "elicitation_id": elicitation_id,
        "choice": choice,
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


def build_guide_card(
    *,
    signing_secret: str,
    agent_id: str,
    workspace_id: str | None,
    has_active_session: bool = False,
    setup_required: bool = False,
    surface_actions: tuple[str, ...] | list[str] | None = None,
    nonce_factory: NonceFactory | None = None,
) -> dict[str, object]:
    """Return the repeatable entry card for one Feishu chat."""
    nonce = nonce_factory or (lambda _action: secrets.token_urlsafe(18))

    def button(action: str, label: str, *, primary: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
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
        if primary:
            result["type"] = "primary"
        return result

    workspace_note = (
        "尚未配置工作目录。请先添加在线主机上的工作目录，再创建任务。"
        if setup_required
        else f"当前工作目录：{workspace_id}"
        if workspace_id
        else "尚未选择工作目录。"
    )
    selected = set(surface_actions or ("quick_commands", "manage_devices", "switch_workspace"))
    entries = [
        ("quick_commands", "⚡ 快捷指令"),
        ("manage_devices", "🖥️ 管理设备"),
        ("switch_workspace", "📁 工作区"),
        ("current_run", "📊 当前任务"),
        ("stop_session", "⏹️ 终止会话"),
        ("help", "❓ 帮助"),
    ]
    actions = [
        button(action, label)
        for action, label in entries
        if action in selected
        and (action not in {"current_run", "stop_session"} or has_active_session)
    ]
    return {
        "config": {"wide_screen_mode": True, "update_multi": True, "enable_forward": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "Omnigent · 开始工作"},
        },
        "elements": [
            {
                "tag": "markdown",
                "content": "**你好，我是你的开发协作助手。**\n"
                "我可以在当前目录中分析项目、推进开发、排查问题，并持续汇报进度。",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": f"**工作位置**\n{workspace_note}",
            },
            {
                "tag": "markdown",
                "content": "**我能帮你推进**\n"
                "• 理解当前项目、定位入口和改动影响\n"
                "• 实现功能、修复问题、运行测试和审查代码\n"
                "• 拆分任务、协调多个 Agent，并在需要拍板时找你确认",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "**试试这样对我说**\n"
                "`先熟悉一下当前项目，告诉我入口、模块和怎么启动`\n"
                "`检查当前分支改了什么，帮我做一次代码审查`\n"
                "`跑相关测试；失败的话定位原因并尝试修复`",
            },
            {
                "tag": "markdown",
                "content": "**快捷指令**\n• `/new` 开启全新会话\n• `/stop` 停止当前会话",
            },
            {"tag": "hr"},
            *([{"tag": "action", "actions": actions}] if actions else []),
        ],
    }


def build_workspace_picker_card(
    workspaces: list[tuple[str, str]],
    *,
    signing_secret: str,
    agent_id: str,
    nonce_factory: NonceFactory | None = None,
) -> dict[str, object]:
    nonce = nonce_factory or (lambda _action: secrets.token_urlsafe(18))
    actions = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": workspace},
            "value": action_value(
                "switch_workspace",
                signing_secret=signing_secret,
                nonce=nonce(workspace),
                agent_id=agent_id,
                workspace_id=workspace,
                host_id=host_id,
            ),
        }
        for workspace, host_id in workspaces[:12]
    ]
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "切换 Workspace"}},
        "elements": [
            {"tag": "markdown", "content": "选择后，新任务会在该目录运行。"},
            {"tag": "action", "actions": actions}
            if actions
            else {"tag": "markdown", "content": "还没有可切换的 Workspace。"},
        ],
    }


def build_quick_commands_card(
    *,
    signing_secret: str,
    agent_id: str,
    has_active_session: bool,
) -> dict[str, object]:
    entries = [("new_session", "✨ 新建会话")]
    if has_active_session:
        entries.append(("stop_session", "⏹️ 终止当前会话"))
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "快捷指令"}},
        "elements": [
            {"tag": "markdown", "content": "选择要执行的会话操作。"},
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
                            agent_id=agent_id,
                        ),
                    }
                    for action, label in entries
                ],
            },
        ],
    }


def build_device_picker_card(
    hosts: list[tuple[str, str]], *, signing_secret: str, agent_id: str
) -> dict[str, object]:
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "管理设备"}},
        "elements": [
            {"tag": "markdown", "content": "选择后，后续新会话将在该设备上运行。"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": f"🖥️ {name}"},
                        "value": action_value(
                            "manage_devices",
                            signing_secret=signing_secret,
                            nonce=secrets.token_urlsafe(18),
                            agent_id=agent_id,
                            host_id=host_id,
                        ),
                    }
                    for host_id, name in hosts[:10]
                ],
            }
            if hosts
            else {"tag": "markdown", "content": "当前没有在线设备。"},
        ],
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


def build_elicitation_card(
    prompt: str,
    options: list[str],
    *,
    signing_secret: str,
    elicitation_id: str,
    agent_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, object]:
    """Render an Inbox-style single-choice question as native Feishu buttons."""
    actions = []
    for index, option in enumerate(options[:10], start=1):
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"{index}. {option}"},
                "value": action_value(
                    "elicitation_choice",
                    signing_secret=signing_secret,
                    nonce=secrets.token_urlsafe(18),
                    agent_id=agent_id,
                    workspace_id=workspace_id,
                    elicitation_id=elicitation_id,
                    choice=option,
                ),
            }
        )
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "需要你的选择"}},
        "body": {
            "elements": [
                {"tag": "markdown", "content": prompt[:4000]},
                {"tag": "action", "actions": actions},
            ]
        },
    }


__all__ = [
    "ALLOWED_ACTIONS",
    "APPROVAL_ACTIONS",
    "PERSISTENT_ACTIONS",
    "action_value",
    "build_device_picker_card",
    "build_elicitation_card",
    "build_guide_card",
    "build_quick_commands_card",
    "build_run_card",
    "build_workspace_card",
    "build_workspace_menu",
    "build_workspace_picker_card",
    "sign_action_payload",
    "verify_action_value",
]
