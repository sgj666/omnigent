"""Agent-scoped Feishu chat routing through authenticated Core HTTP only."""

from __future__ import annotations

from dataclasses import dataclass

from omnigent_feishu.cards import verify_action_value
from omnigent_feishu.core_client import CoreClient, RunCreateCommand
from omnigent_feishu.protocol import FeishuCardAction, FeishuMessage
from omnigent_feishu.store import FeishuStore


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
            await self._store.fail_event(event.event_id, "unknown_binding")
            raise FeishuRoutingError("unknown_binding", "Chat is not bound to an Agent")
        if binding.allowed_members and event.sender_id not in binding.allowed_members:
            await self._store.fail_event(event.event_id, "forbidden")
            raise FeishuRoutingError("forbidden", "Sender is not allowed")
        response = await self._core.create_run(
            RunCreateCommand(
                agent_id=binding.agent_id,
                workspace_id=binding.workspace_id,
                input=event.text,
                source_event_id=f"feishu:{event.event_id}",
                host_id=binding.host_id,
                execution_mode=binding.execution_mode,
            )
        )
        run_id = str(response["id"])
        await self._store.set_binding_run(binding.id, run_id)
        await self._store.complete_event(event.event_id, run_id)
        return RouteResult(event.event_id, run_id, duplicate=not claimed, payload=response)

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
            raise FeishuRoutingError("unknown_binding", "Chat is not bound")
        if binding.allowed_members and event.sender_id not in binding.allowed_members:
            raise FeishuRoutingError("forbidden", "Sender is not allowed")
        value = event.value
        if value.get("agent_id") not in (None, binding.agent_id):
            raise FeishuRoutingError("binding_mismatch", "Agent binding mismatch")
        action = event.action_id
        run_id = str(value.get("run_id") or binding.run_id or "")
        payload: object
        if action == "switch_workspace":
            workspace_id = value.get("workspace_id")
            if not isinstance(workspace_id, str) or not workspace_id:
                payload = await self._core.list_workspaces()
            else:
                await self._store.set_binding_workspace(binding.id, workspace_id)
                payload = {"workspace_id": workspace_id}
        elif action in {"current_run", "run_logs"}:
            if not run_id:
                raise FeishuRoutingError("no_current_run", "No current Run")
            payload = (
                await self._core.get_run(run_id)
                if action == "current_run"
                else await self._core.get_run_inspector(run_id)
            )
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
        elif action in {"list_runs", "create_run", "help"}:
            payload = {"action": action}
        else:
            raise FeishuRoutingError("action_forbidden", "Action is not allowed")
        await self._store.complete_event(event.event_id, run_id)
        return RouteResult(event.event_id, run_id or None, duplicate=not claimed, payload=payload)


LarkRouter = FeishuRouter
LarkRoutingError = FeishuRoutingError

__all__ = ["FeishuRouter", "FeishuRoutingError", "RouteResult"]
