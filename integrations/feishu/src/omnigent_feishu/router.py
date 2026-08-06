"""Agent-scoped Feishu chat routing through authenticated Core HTTP only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from omnigent_feishu.cards import (
    action_value,
    build_device_picker_card,
    build_guide_card,
    build_quick_commands_card,
    build_workspace_picker_card,
    verify_action_value,
)
from omnigent_feishu.core_client import CoreApiError, CoreClient, SessionCreateCommand
from omnigent_feishu.models import ThreadBinding
from omnigent_feishu.protocol import FeishuCardAction, FeishuMenuAction, FeishuMessage
from omnigent_feishu.store import FeishuStore
from omnigent_feishu.surface_profile import surface_profile

_MENU_EVENT_ACTIONS = {
    "session_new": "new_session",
    "quick_new": "new_session",
    "new_session": "new_session",
    "session_stop": "stop_session",
    "quick_stop": "stop_session",
    "stop_session": "stop_session",
    "quick_commands": "quick_commands",
    "manage_devices": "manage_devices",
    "switch_workspace": "switch_workspace",
    "workspace_switch": "switch_workspace",
    "current_run": "current_run",
    "help": "help",
}

_ACTION_CAPABILITIES = {
    "quick_commands": {"quick_commands"},
    "new_session": {"quick_commands"},
    "create_run": {"quick_commands"},
    "stop_session": {"quick_commands", "stop_session"},
    "manage_devices": {"manage_devices"},
    "switch_workspace": {"switch_workspace"},
    "current_run": {"current_run"},
    "help": {"help"},
}


class FeishuRoutingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RouteResult:
    event_id: str
    run_id: str | None
    duplicate: bool = False
    payload: object | None = None


class FeishuRouter:
    """Every free-text message creates or reuses one root Agent Run."""

    def __init__(
        self,
        store: FeishuStore,
        core: CoreClient,
        *,
        action_secret: str,
    ) -> None:
        self._store = store
        self._core = core
        self._action_secret = action_secret
        self._binding_locks: dict[str, asyncio.Lock] = {}

    async def _continue_session(
        self, binding_id: str, session_id: str, text: str
    ) -> tuple[object, str | None]:
        lock = self._binding_locks.setdefault(binding_id, asyncio.Lock())
        async with lock:
            while True:
                session = await self._core.get_session(session_id)
                status = session.get("status") if isinstance(session, dict) else None
                if status not in {"launching", "running", "waiting"}:
                    break
                await asyncio.sleep(1)
            items = await self._core.get_session_items(session_id)
            baseline_id = _latest_assistant_id(items)
            response = await self._core.send_session_input(session_id, text)
            return response, baseline_id

    async def _begin_new_session(self, binding: ThreadBinding) -> ThreadBinding:
        """Create an empty Core session so a user-visible new chat takes effect now."""
        if not binding.workspace_id or not binding.host_id:
            return binding
        response = await self._core.create_session(
            SessionCreateCommand(
                agent_id=binding.agent_id,
                workspace=binding.workspace_id,
                host_id=binding.host_id,
            )
        )
        session_id = str(response["id"])
        await self._store.set_binding_run(binding.id, session_id)
        await self._store.set_binding_root_session(binding.id, session_id)
        refreshed = await self._store.get_binding(
            binding.installation_id, binding.chat_id, binding.thread_id
        )
        assert refreshed is not None
        return refreshed

    async def route(self, event: FeishuMessage, installation_id: str | None = None) -> RouteResult:
        installation_id = installation_id or str(event.raw.get("installation_id", ""))
        if not installation_id:
            raise FeishuRoutingError("unknown_installation", "Installation is required")
        claimed, record = await self._store.claim_event(
            event.event_id, installation_id, event.sender_id
        )
        if not claimed and record.status == "completed" and record.run_id:
            return RouteResult(event.event_id, record.run_id, duplicate=True)
        binding = await self._store.get_binding(installation_id, event.chat_id, event.thread_id)
        if binding is None:
            installation = await self._store.get_installation(installation_id)
            if installation is None or installation.status != "connected":
                await self._store.fail_event(event.event_id, "unknown_binding")
                raise FeishuRoutingError("unknown_binding", "Chat is not bound to an Agent")
            binding = await self._store.bind_thread(
                installation_id=installation_id,
                chat_id=event.chat_id,
                thread_id=event.thread_id,
                agent_id=installation.agent_id,
                workspace_id=installation.default_workspace,
                host_id=installation.default_host_id,
                # A binding represents one Feishu conversation (and optional topic),
                # not its first speaker. Every group member therefore continues the
                # same shared conversation.
                allowed_members=(),
            )
        if not binding.workspace_id or not binding.host_id:
            installation = await self._store.get_installation(installation_id)
            if installation and installation.default_workspace and installation.default_host_id:
                await self._store.set_binding_workspace_scope(
                    binding.id,
                    workspace=installation.default_workspace,
                    host_id=installation.default_host_id,
                )
                binding = await self._store.get_binding(
                    installation_id, event.chat_id, event.thread_id
                )
                assert binding is not None
        if event.chat_type == "p2p":
            await self._store.set_p2p_chat_binding(installation_id, event.sender_id, event.chat_id)
        root_session_id = await self._store.get_binding_root_session(binding.id)
        command = event.text.strip().lower()
        if command in {"/stop", "/new", "/reset"}:
            if root_session_id:
                try:
                    await self._core.stop_session(root_session_id)
                except CoreApiError as exc:
                    if exc.status_code != 404:
                        raise
            if command in {"/new", "/reset"}:
                await self._store.reset_binding_session(binding.id)
            if command in {"/new", "/reset"}:
                binding = await self._store.get_binding(
                    installation_id, event.chat_id, event.thread_id
                )
                assert binding is not None
                binding = await self._begin_new_session(binding)
                await self._store.complete_event(event.event_id, binding.run_id or "command")
                return RouteResult(
                    event.event_id,
                    binding.run_id,
                    payload=await self._guide_payload(
                        binding, message="已新建会话。请直接发送任务。"
                    ),
                )
            await self._store.complete_event(event.event_id, binding.run_id or "command")
            return RouteResult(
                event.event_id,
                binding.run_id,
                payload={
                    "command": command,
                    "message": (
                        "当前会话已停止。下一条消息仍会继续当前上下文。"
                        if command == "/stop"
                        else "已新建会话。下一条消息将从全新上下文开始。"
                    ),
                },
            )
        if _is_greeting(event.text):
            await self._store.complete_event(event.event_id, binding.run_id or "guide")
            return RouteResult(
                event.event_id, binding.run_id, payload=await self._guide_payload(binding)
            )
        if not binding.workspace_id or not binding.host_id:
            await self._store.complete_event(event.event_id, "workspace_required")
            return RouteResult(
                event.event_id,
                None,
                payload={"setup_required": True, "code": "workspace_required"},
            )
        if root_session_id and binding.run_id:
            try:
                response, baseline_id = await self._continue_session(
                    binding.id, root_session_id, event.text
                )
            except CoreApiError as exc:
                if exc.status_code != 404:
                    await self._store.fail_event(event.event_id, "session_input_failed")
                    raise
            else:
                await self._store.complete_event(event.event_id, binding.run_id)
                return RouteResult(
                    event.event_id,
                    binding.run_id,
                    duplicate=not claimed,
                    payload={
                        "id": binding.run_id,
                        "root_session_id": root_session_id,
                        "continued": True,
                        "baseline_assistant_id": baseline_id,
                        "event": response,
                    },
                )

        response = await self._core.create_session(
            SessionCreateCommand(
                agent_id=binding.agent_id,
                workspace=binding.workspace_id,
                host_id=binding.host_id,
            )
        )
        session_id = str(response["id"])
        await self._core.send_session_input(session_id, event.text)
        await self._store.set_binding_run(binding.id, session_id)
        await self._store.set_binding_root_session(binding.id, session_id)
        await self._store.complete_event(event.event_id, session_id)
        return RouteResult(
            event.event_id,
            session_id,
            duplicate=not claimed,
            payload={"id": session_id, "root_session_id": session_id, "event": response},
        )

    async def route_action(self, event: FeishuCardAction, installation_id: str) -> RouteResult:
        claimed, record = await self._store.claim_event(
            event.event_id, installation_id, event.sender_id
        )
        if not claimed and record.status == "completed":
            return RouteResult(event.event_id, record.run_id, duplicate=True)
        if not verify_action_value(event.value, self._action_secret):
            await self._store.fail_event(event.event_id, "invalid_action_signature")
            raise FeishuRoutingError("invalid_action_signature", "Action is invalid")
        binding = await self._store.get_binding(installation_id, event.chat_id, event.thread_id)
        if binding is None:
            installation = await self._store.get_installation(installation_id)
            if installation is None or installation.status != "connected":
                raise FeishuRoutingError("unknown_binding", "Chat is not bound")
            binding = await self._store.bind_thread(
                installation_id=installation_id,
                chat_id=event.chat_id,
                thread_id=event.thread_id,
                agent_id=installation.agent_id,
                workspace_id=installation.default_workspace,
                host_id=installation.default_host_id,
                allowed_members=(),
            )
        value = event.value
        if value.get("agent_id") not in (None, binding.agent_id):
            raise FeishuRoutingError("binding_mismatch", "Agent binding mismatch")
        action = event.action_id
        if not await self._action_enabled(binding.agent_id, action):
            await self._store.fail_event(event.event_id, "action_disabled")
            raise FeishuRoutingError("action_disabled", f"{action} is not enabled for this Agent")
        run_id = str(value.get("run_id") or binding.run_id or "")
        payload: object
        if action == "elicitation_choice":
            elicitation_id = value.get("elicitation_id")
            choice = value.get("choice")
            if not isinstance(elicitation_id, str) or not isinstance(choice, str):
                raise FeishuRoutingError("invalid_elicitation", "Elicitation choice is incomplete")
            if not binding.run_id:
                raise FeishuRoutingError("no_current_run", "No current session")
            payload = await self._core.resolve_elicitation(
                binding.run_id, elicitation_id, content={"answer": choice, "choice": choice}
            )
        elif action == "new_session" or action == "create_run":
            root_session_id = await self._store.get_binding_root_session(binding.id)
            if root_session_id:
                try:
                    await self._core.stop_session(root_session_id)
                except CoreApiError as exc:
                    if exc.status_code != 404:
                        raise
            await self._store.reset_binding_session(binding.id)
            binding = await self._store.get_binding(
                installation_id, event.chat_id, event.thread_id
            )
            assert binding is not None
            binding = await self._begin_new_session(binding)
            run_id = binding.run_id or ""
            payload = await self._guide_payload(
                binding, message="已准备好新会话。请直接发送任务。"
            )
        elif action == "stop_session":
            root_session_id = await self._store.get_binding_root_session(binding.id)
            if not root_session_id:
                payload = await self._guide_payload(binding, message="当前没有正在进行的会话。")
            else:
                try:
                    await self._core.stop_session(root_session_id)
                except CoreApiError as exc:
                    if exc.status_code != 404:
                        raise
                await self._store.reset_binding_session(binding.id)
                binding = await self._store.get_binding(
                    installation_id, event.chat_id, event.thread_id
                )
                assert binding is not None
                payload = await self._guide_payload(binding, message="当前会话已终止。")
        elif action == "quick_commands":
            payload = {
                "guide_card": build_quick_commands_card(
                    signing_secret=self._action_secret,
                    agent_id=binding.agent_id,
                    has_active_session=bool(binding.run_id),
                )
            }
        elif action == "manage_devices":
            host_id = value.get("host_id")
            hosts_payload = await self._core.list_hosts()
            rows = hosts_payload.get("hosts") if isinstance(hosts_payload, dict) else []
            if not isinstance(rows, list) and isinstance(hosts_payload, dict):
                rows = hosts_payload.get("data", [])
            if not isinstance(rows, list):
                rows = []
            hosts = [
                (str(row["host_id"]), str(row.get("name") or row["host_id"]))
                for row in rows
                if isinstance(row, dict)
                and row.get("status") == "online"
                and isinstance(row.get("host_id"), str)
            ]
            if not isinstance(host_id, str) or not host_id:
                payload = {
                    "guide_card": build_device_picker_card(
                        hosts,
                        signing_secret=self._action_secret,
                        agent_id=binding.agent_id,
                    )
                }
            elif host_id not in {item[0] for item in hosts}:
                raise FeishuRoutingError("host_unavailable", "Host is not online")
            else:
                scopes = await self._store.list_agent_workspace_scopes(
                    binding.agent_id, host_id=host_id
                )
                if not scopes:
                    payload = await self._guide_payload(
                        binding,
                        message="该设备还没有授权目录，请先在 Omnigent 的飞书连接设置中添加。",
                    )
                else:
                    await self._store.set_binding_workspace_scope(
                        binding.id, workspace=scopes[0][0], host_id=host_id
                    )
                    binding = await self._store.get_binding(
                        installation_id, event.chat_id, event.thread_id
                    )
                    assert binding is not None
                    payload = await self._guide_payload(
                        binding, message=f"已切换设备：{dict(hosts)[host_id]}"
                    )
        elif action == "switch_workspace":
            workspace_id = value.get("workspace_id")
            host_id = value.get("host_id")
            if not isinstance(workspace_id, str) or not workspace_id:
                payload = await self._workspace_picker_payload(binding)
            else:
                scopes = await self._store.list_agent_workspace_scopes(binding.agent_id)
                if not isinstance(host_id, str) or (workspace_id, host_id) not in scopes:
                    raise FeishuRoutingError("workspace_forbidden", "Workspace is not authorized")
                await self._store.set_binding_workspace_scope(
                    binding.id, workspace=workspace_id, host_id=host_id
                )
                binding = await self._store.get_binding(
                    installation_id, event.chat_id, event.thread_id
                )
                assert binding is not None
                payload = await self._guide_payload(binding, message=f"已切换到：{workspace_id}")
        elif action == "create_workspace":
            if not binding.host_id:
                payload = await self._guide_payload(binding, setup_required=True)
            else:
                payload = {
                    "message": "请在 Omnigent 的飞书连接设置中选择在线主机和本地工作目录。",
                    "guide_card": await self._guide_card(binding, setup_required=True),
                }
        elif action == "create_task":
            payload = {
                "message": "请直接发送任务描述。我会在当前 Workspace 中创建并持续更新这次 Run。",
                "guide_card": await self._guide_card(
                    binding, setup_required=not bool(binding.workspace_id)
                ),
            }
        elif action in {"current_run", "run_logs"}:
            if not run_id:
                raise FeishuRoutingError("no_current_run", "No current Run")
            if action == "current_run":
                session = await self._core.get_session(run_id)
                status = (
                    session.get("status", "unknown") if isinstance(session, dict) else "unknown"
                )
                payload = {"message": f"当前任务状态：{status}\nSession：{run_id}"}
            else:
                payload = await self._core.get_run_inspector(run_id)
        elif action == "stop_run":
            if not run_id:
                raise FeishuRoutingError("no_current_run", "No current Run")
            payload = await self._core.stop_run(run_id)
        elif action in {"approve", "deny"}:
            approval_id = value.get("approval_id")
            if not run_id or not isinstance(approval_id, str) or not approval_id:
                raise FeishuRoutingError("invalid_approval", "Approval context is missing")
            payload = await self._core.decide_approval(
                run_id, approval_id, approved=action == "approve"
            )
        elif action == "help":
            payload = await self._guide_payload(binding)
        elif action == "list_runs":
            payload = {"action": action}
        else:
            raise FeishuRoutingError("action_forbidden", "Action is not allowed")
        await self._store.complete_event(event.event_id, run_id)
        return RouteResult(event.event_id, run_id or None, duplicate=not claimed, payload=payload)

    async def route_menu_action(
        self, event: FeishuMenuAction, installation_id: str
    ) -> RouteResult:
        action = _MENU_EVENT_ACTIONS.get(event.event_key)
        if action is None:
            raise FeishuRoutingError("unknown_menu_action", "Unknown bot menu event_key")
        binding = await self._store.get_p2p_chat_binding(installation_id, event.sender_id)
        if binding is None:
            raise FeishuRoutingError(
                "p2p_binding_required",
                "Send one direct message before using the bot menu",
            )
        value = action_value(
            action,
            signing_secret=self._action_secret,
            nonce=event.event_id,
            agent_id=binding.agent_id,
            run_id=binding.run_id,
        )
        return await self.route_action(
            FeishuCardAction(
                event.event_id,
                action,
                event.event_id,
                binding.chat_id,
                binding.thread_id or None,
                event.sender_id,
                value,
            ),
            installation_id,
        )

    async def _action_enabled(self, agent_id: str, action: str) -> bool:
        required = _ACTION_CAPABILITIES.get(action)
        if required is None:
            return True
        profile = surface_profile(await self._store.get_agent_surface_profile(agent_id))
        selected = profile.get("actions")
        return isinstance(selected, list) and bool(required.intersection(selected))

    async def _guide_card(
        self, binding: ThreadBinding, *, setup_required: bool = False
    ) -> dict[str, object]:
        profile = await self._store.get_agent_surface_profile(binding.agent_id)
        actions = profile.get("actions") if profile is not None else None
        return build_guide_card(
            signing_secret=self._action_secret,
            agent_id=binding.agent_id,
            workspace_id=binding.workspace_id,
            has_active_session=bool(binding.run_id),
            setup_required=setup_required,
            surface_actions=actions if isinstance(actions, list) else None,
        )

    async def _guide_payload(
        self,
        binding: ThreadBinding,
        *,
        message: str | None = None,
        setup_required: bool = False,
    ) -> dict[str, object]:
        return {
            "guide_card": await self._guide_card(binding, setup_required=setup_required),
            "message": message,
        }

    async def _workspace_picker_payload(self, binding: ThreadBinding) -> dict[str, object]:
        scopes = await self._store.list_agent_workspace_scopes(binding.agent_id)
        return {
            "guide_card": build_workspace_picker_card(
                scopes, signing_secret=self._action_secret, agent_id=binding.agent_id
            )
        }


LarkRouter = FeishuRouter
LarkRoutingError = FeishuRoutingError

__all__ = ["FeishuRouter", "FeishuRoutingError", "RouteResult"]


def _latest_assistant_id(payload: object) -> str | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    for item in reversed(payload["data"]):
        if (
            isinstance(item, dict)
            and item.get("type") == "message"
            and item.get("role") == "assistant"
        ):
            item_id = item.get("id")
            return item_id if isinstance(item_id, str) else None
    return None


def _is_greeting(text: str) -> bool:
    normalized = "".join(text.strip().lower().split())
    return normalized in {"你好", "您好", "嗨", "哈喽", "在吗", "hi", "hello", "hey"}
