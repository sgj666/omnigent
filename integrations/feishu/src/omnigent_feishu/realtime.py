"""Receive PersonalAgent messages through Feishu's long connection."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

from omnigent_feishu.adapter import FeishuAdapter
from omnigent_feishu.cards import build_elicitation_card, build_guide_card
from omnigent_feishu.core_client import CoreApiError, CoreClient
from omnigent_feishu.credentials import FeishuCredentialCipher
from omnigent_feishu.models import Installation
from omnigent_feishu.router import FeishuRoutingError
from omnigent_feishu.store import FeishuStore

logger = logging.getLogger(__name__)


class FeishuRealtimeRuntime:
    def __init__(
        self,
        store: FeishuStore,
        cipher: FeishuCredentialCipher,
        adapter: FeishuAdapter,
        core: CoreClient,
        *,
        action_secret: str = "",
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._adapter = adapter
        self._core = core
        self._action_secret = action_secret
        self._app_loop: asyncio.AbstractEventLoop | None = None
        self._started: set[str] = set()
        self._delivery_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._app_loop = asyncio.get_running_loop()
        for installation in await self._store.connected_installations():
            try:
                await self.start_installation(installation)
            except Exception:
                logger.exception(
                    "feishu_installation_start_failed installation_id=%s; rebind required",
                    installation.id,
                )
                await self._store.mark_installation_error(
                    installation.id, "credential_key_changed_rebind_required"
                )

    async def start_installation(self, installation: Installation) -> None:
        if not installation.app_id or not installation.app_secret_ciphertext:
            return
        if installation.app_id in self._started:
            return
        secret = self._cipher.decrypt(installation.app_secret_ciphertext)
        self._started.add(installation.app_id)
        # v3 refreshes the guide card layout after the former passive connection notice.
        welcome_key = f"welcome_sent:{installation.id}:v3"
        if installation.installer_open_id and not await self._store.get_meta(welcome_key):
            profile = await self._store.get_agent_surface_profile(installation.agent_id)
            actions = profile.get("actions") if profile is not None else None
            await self._send_interactive_card(
                installation.app_id,
                secret,
                installation.installer_open_id,
                "open_id",
                build_guide_card(
                    signing_secret=self._action_secret,
                    agent_id=installation.agent_id,
                    workspace_id=installation.default_workspace,
                    setup_required=not bool(installation.default_workspace),
                    surface_actions=actions if isinstance(actions, list) else None,
                ),
            )
            await self._store.set_meta(welcome_key, "1")
        thread = threading.Thread(
            target=self._listen,
            args=(installation, secret),
            name=f"feishu-{installation.id[:8]}",
            daemon=True,
        )
        thread.start()

    def _listen(self, installation: Installation, secret: str) -> None:
        def receive(event: Any) -> None:
            if self._app_loop is None:
                return
            future = asyncio.run_coroutine_threadsafe(
                self._receive(installation, secret, event), self._app_loop
            )
            future.add_done_callback(self._log_failure)

        def receive_action(event: Any) -> P2CardActionTriggerResponse:
            if self._app_loop is not None:
                future = asyncio.run_coroutine_threadsafe(
                    self._receive_action(installation, secret, event), self._app_loop
                )
                future.add_done_callback(self._log_failure)
            return P2CardActionTriggerResponse()

        def receive_menu(event: Any) -> None:
            if self._app_loop is None:
                return
            future = asyncio.run_coroutine_threadsafe(
                self._receive_menu(installation, secret, event), self._app_loop
            )
            future.add_done_callback(self._log_failure)

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(receive)
            .register_p2_card_action_trigger(receive_action)
            .register_p2_application_bot_menu_v6(receive_menu)
            .register_p2_im_message_reaction_created_v1(lambda _event: None)
            .register_p2_im_message_reaction_deleted_v1(lambda _event: None)
            .build()
        )
        try:
            logger.info("feishu_listener_start installation_id=%s", installation.id)
            lark.ws.Client(
                installation.app_id,
                secret,
                event_handler=handler,
                auto_reconnect=True,
            ).start()
        except Exception:
            logger.exception("Feishu long connection stopped for %s", installation.id)
            if installation.app_id:
                self._started.discard(installation.app_id)

    @staticmethod
    def _log_failure(future: Any) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("Failed to process Feishu message")

    async def _receive(self, installation: Installation, secret: str, event: Any) -> None:
        message = event.event.message
        sender = event.event.sender.sender_id
        event_id = event.header.event_id
        logger.info(
            "feishu_event_received installation_id=%s event_id=%s message_type=%s",
            installation.id,
            event_id,
            message.message_type,
        )
        payload = {
            "schema": event.schema,
            "header": {
                "event_id": event_id,
                "event_type": event.header.event_type,
                "app_id": event.header.app_id,
            },
            "event": {
                "sender": {"sender_id": {"open_id": sender.open_id}},
                "message": {
                    "message_id": message.message_id,
                    "chat_id": message.chat_id,
                    "thread_id": message.thread_id,
                    "root_id": message.root_id,
                    "chat_type": message.chat_type,
                    "message_type": message.message_type,
                    "content": message.content,
                },
            },
        }
        reaction_id: str | None = None
        try:
            reaction_id = await self._add_reaction(
                installation.app_id or "", secret, message.message_id, "Typing"
            )
            logger.info(
                "feishu_reaction_added installation_id=%s event_id=%s emoji=Typing",
                installation.id,
                event_id,
            )
        except Exception:
            logger.exception(
                "feishu_reaction_add_failed installation_id=%s event_id=%s",
                installation.id,
                event_id,
            )
        try:
            logger.info(
                "feishu_event_routing installation_id=%s event_id=%s",
                installation.id,
                event_id,
            )
            result = await self._adapter.receive(
                json.dumps(payload).encode(), {}, installation_id=installation.id
            )
            run_id = result.response.get("run_id") if isinstance(result.response, dict) else None
            logger.info(
                "feishu_run_created installation_id=%s event_id=%s run_id=%s",
                installation.id,
                event_id,
                run_id,
            )
            root_session_id = (
                result.response["run"].get("root_session_id")
                if isinstance(result.response, dict)
                and isinstance(result.response.get("run"), dict)
                else None
            )
            details_session_id = (
                root_session_id
                if isinstance(root_session_id, str) and root_session_id
                else run_id
                if isinstance(run_id, str) and run_id
                else None
            )
            if details_session_id:
                await self.sync_agent_surface(installation.agent_id)
            baseline_assistant_id = (
                result.response["run"].get("baseline_assistant_id")
                if isinstance(result.response, dict)
                and isinstance(result.response.get("run"), dict)
                else None
            )
            command_message = (
                result.response["run"].get("message")
                if isinstance(result.response, dict)
                and isinstance(result.response.get("run"), dict)
                and isinstance(result.response["run"].get("command"), str)
                else None
            )
            guide_card = (
                result.response["run"].get("guide_card")
                if isinstance(result.response, dict)
                and isinstance(result.response.get("run"), dict)
                else None
            )
            if isinstance(guide_card, dict):
                if reaction_id:
                    await self._delete_reaction(
                        installation.app_id or "", secret, message.message_id, reaction_id
                    )
                try:
                    await self._send_interactive_card(
                        installation.app_id or "", secret, message.chat_id, "chat_id", guide_card
                    )
                except (httpx.HTTPError, RuntimeError):
                    # A presentation failure must never turn a completed command into a
                    # user-visible command failure. The text returned by Core is the
                    # durable confirmation; the card is only the richer follow-up UI.
                    logger.exception("feishu_guide_card_send_failed; falling back to text")
                    if isinstance(command_message, str):
                        await self._send_text(
                            installation.app_id or "", secret, message.chat_id, command_message
                        )
                return
            if isinstance(command_message, str):
                if reaction_id:
                    await self._delete_reaction(
                        installation.app_id or "", secret, message.message_id, reaction_id
                    )
                await self._send_text(
                    installation.app_id or "", secret, message.chat_id, command_message
                )
                return
            setup_required = (
                result.response["run"].get("setup_required")
                if isinstance(result.response, dict)
                and isinstance(result.response.get("run"), dict)
                else False
            )
            if setup_required:
                if reaction_id:
                    await self._delete_reaction(
                        installation.app_id or "", secret, message.message_id, reaction_id
                    )
                await self._send_text(
                    installation.app_id or "",
                    secret,
                    message.chat_id,
                    "请先在 Omnigent 的“连接飞书”中选择在线主机和本地工作目录，"
                    "再发送消息。目录可以是包含多个 Git 项目的非 Git 目录。",
                )
                return
            if run_id and isinstance(root_session_id, str) and root_session_id:
                card_message_id = await self._send_card(
                    installation.app_id or "",
                    secret,
                    message.chat_id,
                    "chat_id",
                    "正在处理",
                    "已收到消息，正在分析…",
                )
                delivery_task = asyncio.create_task(
                    self._deliver_result(
                        installation,
                        secret,
                        message.chat_id,
                        run_id,
                        root_session_id,
                        event_id,
                        message.message_id,
                        reaction_id,
                        card_message_id,
                        baseline_assistant_id if isinstance(baseline_assistant_id, str) else None,
                    )
                )
                self._delivery_tasks.add(delivery_task)
                delivery_task.add_done_callback(self._delivery_tasks.discard)
        except Exception as exc:
            logger.exception(
                "feishu_event_failed installation_id=%s event_id=%s stage=route_or_reply",
                installation.id,
                event_id,
            )
            if reaction_id:
                try:
                    await self._delete_reaction(
                        installation.app_id or "", secret, message.message_id, reaction_id
                    )
                except Exception:
                    logger.exception(
                        "feishu_failure_reaction_failed installation_id=%s event_id=%s",
                        installation.id,
                        event_id,
                    )
            try:
                await self._send_text(
                    installation.app_id or "",
                    secret,
                    message.chat_id,
                    _failure_message(exc),
                )
            except Exception:
                logger.exception(
                    "feishu_failure_reply_failed installation_id=%s event_id=%s",
                    installation.id,
                    event_id,
                )
            raise

    async def _receive_action(self, installation: Installation, secret: str, event: Any) -> None:
        action = event.event.action
        operator = event.event.operator
        context = event.event.context
        payload = {
            "header": {"event_id": event.header.event_id, "event_type": "card.action.trigger"},
            "event": {
                "operator": {"open_id": operator.open_id},
                "action": {
                    "value": action.value or {},
                    "action_id": (action.value or {}).get("action_id"),
                },
                "context": {"open_chat_id": context.open_chat_id},
            },
        }
        result = await self._adapter.receive(
            json.dumps(payload).encode(), {}, installation_id=installation.id
        )
        run = result.response.get("run") if isinstance(result.response, dict) else None
        if not isinstance(run, dict):
            return
        card = run.get("guide_card")
        message = run.get("message")
        receive_id = context.open_chat_id
        if isinstance(card, dict) and isinstance(receive_id, str) and receive_id:
            await self._send_interactive_card(
                installation.app_id or "", secret, receive_id, "chat_id", card
            )
        if isinstance(message, str) and isinstance(receive_id, str) and receive_id:
            await self._send_text(installation.app_id or "", secret, receive_id, message)

    async def _receive_menu(self, installation: Installation, secret: str, event: Any) -> None:
        data = event.event
        operator_id = data.operator.operator_id
        open_id = operator_id.open_id
        event_key = data.event_key
        event_id = event.header.event_id
        if not all(isinstance(item, str) and item for item in (open_id, event_key, event_id)):
            logger.warning("feishu_bot_menu_event_incomplete installation_id=%s", installation.id)
            return
        payload = {
            "header": {
                "event_id": event_id,
                "event_type": "application.bot.menu_v6",
            },
            "event": {
                "operator": {"operator_id": {"open_id": open_id}},
                "event_key": event_key,
            },
        }
        try:
            result = await self._adapter.receive(
                json.dumps(payload).encode(), {}, installation_id=installation.id
            )
            run = result.response.get("run") if isinstance(result.response, dict) else None
            if not isinstance(run, dict):
                return
            card = run.get("guide_card")
            message = run.get("message")
            if isinstance(card, dict):
                await self._send_interactive_card(
                    installation.app_id or "", secret, open_id, "open_id", card
                )
            if isinstance(message, str):
                await self._send_text(
                    installation.app_id or "",
                    secret,
                    open_id,
                    message,
                    receive_id_type="open_id",
                )
        except Exception as exc:
            logger.exception(
                "feishu_bot_menu_event_failed installation_id=%s event_key=%s",
                installation.id,
                event_key,
            )
            await self._send_text(
                installation.app_id or "",
                secret,
                open_id,
                _failure_message(exc),
                receive_id_type="open_id",
            )

    async def _deliver_result(
        self,
        installation: Installation,
        secret: str,
        chat_id: str,
        run_id: str,
        session_id: str,
        event_id: str,
        message_id: str,
        reaction_id: str | None,
        card_message_id: str,
        baseline_assistant_id: str | None,
    ) -> None:
        last_text = ""
        last_reply_id: str | None = None
        progress: list[str] = []
        sent_elicitations: set[str] = set()
        idle_without_workers = 0
        for _ in range(900):
            await asyncio.sleep(2)
            try:
                session = await self._core.get_session(session_id)
                items = await self._core.get_session_items(session_id)
            except Exception:
                logger.exception(
                    "feishu_result_poll_failed event_id=%s run_id=%s", event_id, run_id
                )
                continue
            status = session.get("status") if isinstance(session, dict) else None
            await self._send_pending_elicitation_cards(
                installation,
                secret,
                chat_id,
                session,
                sent_elicitations,
            )
            reply = _latest_assistant_reply(items, after_id=baseline_assistant_id)
            text = reply[1] if reply else None
            reply_id = reply[0] if reply else None
            if text and (reply_id != last_reply_id or text != last_text):
                candidate_progress = (
                    [*progress[:-1], text]
                    if reply_id == last_reply_id and progress
                    else [*progress, text]
                )
                if await self._patch_card_safely(
                    installation.app_id or "",
                    secret,
                    card_message_id,
                    f"正在回复 · {len(candidate_progress)} 条回应",
                    _format_progress(candidate_progress, final=False, waiting=status == "waiting"),
                    event_id=event_id,
                    run_id=run_id,
                ):
                    last_text = text
                    last_reply_id = reply_id
                    progress = candidate_progress
            elif not text and status in {"running", "waiting", "launching"}:
                phase = (
                    "⏳ 正在等待协作者完成…" if status == "waiting" else "⏳ 正在思考并组织回复…"
                )
                if phase != last_text:
                    if await self._patch_card_safely(
                        installation.app_id or "",
                        secret,
                        card_message_id,
                        "正在回复",
                        phase,
                        event_id=event_id,
                        run_id=run_id,
                    ):
                        last_text = phase
            if status not in {"idle", "failed", "cancelled", "stopped"}:
                idle_without_workers = 0
                continue
            if status == "idle":
                try:
                    children = await self._core.get_child_sessions(session_id)
                except Exception:
                    logger.exception(
                        "feishu_children_poll_failed event_id=%s run_id=%s", event_id, run_id
                    )
                    continue
                if _has_active_children(children):
                    idle_without_workers = 0
                    continue
                # A Worker completion and the Root auto-wake are separate
                # events. Keep polling briefly after the last child settles
                # so the interim "workers dispatched" answer is not mistaken
                # for the final aggregation.
                idle_without_workers += 1
                if idle_without_workers < 3:
                    continue
            if status == "idle" and not text:
                continue
            if not text:
                text = f"处理失败：Run 状态为 {status}，没有产生可展示的回复。"
            if reaction_id:
                try:
                    await self._delete_reaction(
                        installation.app_id or "", secret, message_id, reaction_id
                    )
                except Exception:
                    logger.exception(
                        "feishu_reaction_clear_failed event_id=%s run_id=%s", event_id, run_id
                    )
            if not await self._patch_card_safely(
                installation.app_id or "",
                secret,
                card_message_id,
                "回复" if status == "idle" else "处理失败",
                _format_progress(progress or [text], final=status == "idle"),
                event_id=event_id,
                run_id=run_id,
            ):
                continue
            logger.info(
                "feishu_result_sent installation_id=%s event_id=%s run_id=%s status=%s",
                installation.id,
                event_id,
                run_id,
                status,
            )
            return
        await self._send_text(
            installation.app_id or "",
            secret,
            chat_id,
            f"Run {run_id} 仍在运行，等待结果超时。",
        )

    async def _send_pending_elicitation_cards(
        self,
        installation: Installation,
        secret: str,
        chat_id: str,
        session: object,
        sent: set[str],
    ) -> None:
        if not isinstance(session, dict) or not isinstance(
            session.get("pending_elicitations"), list
        ):
            return
        for pending in session["pending_elicitations"]:
            if not isinstance(pending, dict):
                continue
            elicitation_id = pending.get("elicitation_id")
            if not isinstance(elicitation_id, str) or elicitation_id in sent:
                continue
            prompt, options = _elicitation_question(pending)
            if not prompt or len(options) < 2:
                continue
            card = build_elicitation_card(
                prompt,
                options,
                signing_secret=self._action_secret,
                elicitation_id=elicitation_id,
            )
            try:
                await self._send_interactive_card(
                    installation.app_id or "", secret, chat_id, "chat_id", card
                )
                sent.add(elicitation_id)
            except Exception:
                logger.exception("feishu_elicitation_card_send_failed")

    async def _patch_card_safely(
        self,
        app_id: str,
        secret: str,
        message_id: str,
        title: str,
        content: str,
        *,
        event_id: str,
        run_id: str,
    ) -> bool:
        """Patch one progress card without losing the result-delivery task on a transient error."""
        try:
            await self._patch_card(app_id, secret, message_id, title, content)
        except Exception:
            logger.exception("feishu_card_patch_failed event_id=%s run_id=%s", event_id, run_id)
            return False
        return True

    @staticmethod
    def _card(title: str, content: str) -> dict[str, object]:
        return {
            "schema": "2.0",
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": title}},
            "body": {"elements": [{"tag": "markdown", "content": content[:28000]}]},
        }

    async def _send_card(
        self,
        app_id: str,
        secret: str,
        receive_id: str,
        receive_id_type: str,
        title: str,
        content: str,
    ) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._tenant_token(client, app_id, secret)
            response = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(self._card(title, content), ensure_ascii=False),
                },
            )
            self._log_card_rejection(response)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                raise RuntimeError(f"Feishu card API rejected the message: {payload.get('code')}")
        return str(payload["data"]["message_id"])

    async def _send_interactive_card(
        self,
        app_id: str,
        secret: str,
        receive_id: str,
        receive_id_type: str,
        card: dict[str, object],
    ) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._tenant_token(client, app_id, secret)
            response = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
            )
            self._log_card_rejection(response)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                raise RuntimeError(f"Feishu card API rejected the message: {payload.get('code')}")
            return str(payload["data"]["message_id"])

    @staticmethod
    def _log_card_rejection(response: httpx.Response) -> None:
        """Log Feishu's safe diagnostic fields without leaking request credentials."""
        if not response.is_error:
            return
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = {}
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("msg") if isinstance(payload, dict) else None
        logger.warning(
            "feishu_interactive_card_rejected status=%s code=%s message=%s",
            response.status_code,
            code,
            message,
        )

    async def _patch_card(
        self, app_id: str, secret: str, message_id: str, title: str, content: str
    ) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._tenant_token(client, app_id, secret)
            response = await client.patch(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"content": json.dumps(self._card(title, content), ensure_ascii=False)},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                raise RuntimeError(f"Feishu card update rejected: {payload.get('code')}")

    async def _send_text(
        self,
        app_id: str,
        secret: str,
        receive_id: str,
        text: str,
        *,
        receive_id_type: str = "chat_id",
    ) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._tenant_token(client, app_id, secret)
            response = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                raise RuntimeError(f"Feishu message API rejected the reply: {payload.get('code')}")

    async def sync_agent_surface(self, agent_id: str) -> dict[str, object]:
        installation = await self._store.get_agent_installation(agent_id)
        binding = await self._store.get_agent_binding(agent_id)
        if (
            installation is None
            or binding is None
            or not binding.run_id
            or not installation.app_id
            or not installation.app_secret_ciphertext
        ):
            result: dict[str, object] = {
                "status": "pending",
                "message": "首次在飞书中启动任务后，将创建执行详情入口。",
            }
            await self._store.set_meta(f"surface_sync:{agent_id}", json.dumps(result))
            return result
        secret = self._cipher.decrypt(installation.app_secret_ciphertext)
        try:
            await self._ensure_details_tab(installation, secret, binding.chat_id, binding.run_id)
        except httpx.HTTPStatusError as exc:
            try:
                payload = exc.response.json()
            except ValueError:
                payload = {}
            if payload.get("code") == 99991672:
                query = urlencode(
                    {
                        "q": "im:chat.tabs:read,im:chat.tabs:write_only",
                        "op_from": "openapi",
                        "token_type": "tenant",
                    }
                )
                result = {
                    "status": "permission_required",
                    "message": "需要开通飞书会话标签页的读写权限。",
                    "permission_url": f"https://open.feishu.cn/app/{installation.app_id}/auth?{query}",
                }
                await self._store.set_meta(f"surface_sync:{agent_id}", json.dumps(result))
                logger.warning(
                    "feishu_details_tab_permission_required installation_id=%s",
                    installation.id,
                )
                return result
            logger.exception(
                "feishu_details_tab_profile_sync_failed installation_id=%s",
                installation.id,
            )
            result = {"status": "unavailable", "message": "飞书执行详情入口同步失败。"}
            await self._store.set_meta(f"surface_sync:{agent_id}", json.dumps(result))
            return result
        except Exception:
            logger.exception(
                "feishu_details_tab_profile_sync_failed installation_id=%s",
                installation.id,
            )
            result = {"status": "unavailable", "message": "飞书执行详情入口同步失败。"}
            await self._store.set_meta(f"surface_sync:{agent_id}", json.dumps(result))
            return result
        result = {"status": "ready", "message": "执行详情入口已同步到飞书。"}
        await self._store.set_meta(f"surface_sync:{agent_id}", json.dumps(result))
        return result

    async def _ensure_details_tab(
        self, installation: Installation, secret: str, chat_id: str, session_id: str
    ) -> None:
        profile = await self._store.get_agent_surface_profile(installation.agent_id)
        if profile is None or not profile.get("details_base_url"):
            return
        base_url = str(profile["details_base_url"]).rstrip("/")
        details_url = f"{base_url}/c/{quote(session_id, safe='')}"
        chat = quote(chat_id, safe="")
        tab_key = f"details_tab:{installation.id}:{chat_id}"
        tab_id = await self._store.get_meta(tab_key)
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._tenant_token(client, installation.app_id or "", secret)
            headers = {"Authorization": f"Bearer {token}"}
            if not tab_id:
                response = await client.get(
                    f"https://open.feishu.cn/open-apis/im/v1/chats/{chat}/chat_tabs/list_tabs",
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                rows = []
                if isinstance(data, dict):
                    for key in ("chat_tabs", "tab_list", "items"):
                        if isinstance(data.get(key), list):
                            rows = data[key]
                            break
                found = next(
                    (
                        row.get("tab_id")
                        for row in rows
                        if isinstance(row, dict)
                        and row.get("tab_name") == "执行详情"
                        and isinstance(row.get("tab_id"), str)
                    ),
                    None,
                )
                tab_id = found if isinstance(found, str) else None
            tab = {
                "tab_name": "执行详情",
                "tab_type": "url",
                "tab_content": {"url": details_url},
            }
            endpoint = f"https://open.feishu.cn/open-apis/im/v1/chats/{chat}/chat_tabs"
            if tab_id:
                tab["tab_id"] = tab_id
                response = await client.post(
                    f"{endpoint}/update_tabs", headers=headers, json={"chat_tabs": [tab]}
                )
            else:
                response = await client.post(endpoint, headers=headers, json={"chat_tabs": [tab]})
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                code = payload.get("code")
                raise RuntimeError(f"Feishu chat tab API rejected the request: {code}")
            if not tab_id:
                data = payload.get("data", {})
                rows = data.get("chat_tabs", []) if isinstance(data, dict) else []
                if rows and isinstance(rows[0], dict) and isinstance(rows[0].get("tab_id"), str):
                    await self._store.set_meta(tab_key, rows[0]["tab_id"])

    @staticmethod
    async def _tenant_token(client: httpx.AsyncClient, app_id: str, secret: str) -> str:
        response = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": secret},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Feishu did not issue a tenant access token")
        return token

    async def _add_reaction(self, app_id: str, secret: str, message_id: str, emoji: str) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._tenant_token(client, app_id, secret)
            response = await client.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
                headers={"Authorization": f"Bearer {token}"},
                json={"reaction_type": {"emoji_type": emoji}},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                raise RuntimeError(
                    f"Feishu reaction API rejected the request: {payload.get('code')}"
                )
            data = payload.get("data", {})
            reaction_id = data.get("reaction_id") if isinstance(data, dict) else None
            if not isinstance(reaction_id, str) or not reaction_id:
                raise RuntimeError("Feishu reaction API did not return reaction_id")
            return reaction_id

    async def _delete_reaction(
        self, app_id: str, secret: str, message_id: str, reaction_id: str
    ) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._tenant_token(client, app_id, secret)
            response = await client.delete(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                raise RuntimeError(f"Feishu reaction delete failed: {payload.get('code')}")


def _failure_message(exc: Exception) -> str:
    """Turn the expected disconnected-host response into an actionable reply."""
    if isinstance(exc, FeishuRoutingError):
        if exc.code == "p2p_binding_required":
            return "请先在当前单聊中发送一条消息，再使用常驻菜单。"
        if exc.code == "action_disabled":
            return "当前 Agent 未启用这个飞书能力，请在 Omnigent 的连接设置中开启。"
        if exc.code == "no_current_run":
            return "当前没有正在进行的任务。"
        if exc.code == "unknown_menu_action":
            return "这个菜单项尚未绑定 Omnigent 动作，请检查飞书后台的 event_key。"
    if isinstance(exc, CoreApiError):
        detail = str(exc.detail).lower()
        if "host" in detail and ("offline" in detail or "not connected" in detail):
            return "本地 Host 未连接，暂时无法新建会话。请启动 Omnigent Host 后重试。"
    return f"处理失败：{type(exc).__name__}"


def _elicitation_question(pending: dict[str, object]) -> tuple[str, list[str]]:
    params = pending.get("params")
    if not isinstance(params, dict):
        return "", []
    prompt = params.get("message") or params.get("prompt") or params.get("question")
    if not isinstance(prompt, str):
        prompt = "请选择一个选项"
    raw_options = params.get("options")
    if not isinstance(raw_options, list):
        schema = params.get("requestedSchema")
        raw_options = schema.get("options") if isinstance(schema, dict) else []
    options: list[str] = []
    for option in raw_options:
        if isinstance(option, str):
            options.append(option)
        elif isinstance(option, dict):
            label = (
                option.get("label")
                or option.get("title")
                or option.get("text")
                or option.get("value")
            )
            if isinstance(label, str) and label:
                options.append(label)
    return prompt, options


def _latest_assistant_reply(
    payload: object, *, after_id: str | None = None
) -> tuple[str | None, str] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    for item in reversed(payload["data"]):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
            continue
        if after_id is not None and item.get("id") == after_id:
            return None
        parts = [
            part.get("text", "")
            for part in item["content"]
            if isinstance(part, dict) and part.get("type") == "output_text"
        ]
        text = "\n".join(part for part in parts if isinstance(part, str) and part)
        if text:
            item_id = item.get("id")
            return (item_id if isinstance(item_id, str) else None, text)
    return None


def _latest_assistant_text(payload: object, *, after_id: str | None = None) -> str | None:
    reply = _latest_assistant_reply(payload, after_id=after_id)
    return reply[1] if reply else None


def _format_progress(entries: list[str], *, final: bool, waiting: bool = False) -> str:
    updates = []
    for index, text in enumerate(entries, start=1):
        label = "本轮总结" if final and index == len(entries) else f"第 {index} 次回应"
        updates.append(f"**{label}**\n\n{text}")
    history = "\n\n---\n\n".join(updates)
    if not final:
        waiting_text = "正在等待协作者完成…" if waiting else "仍在生成下一条回应…"
        return f"{history}\n\n---\n\n⏳ _{waiting_text}_"
    if len(entries) == 1:
        return f"**本轮完成**\n\n{entries[0]}"
    return f"**本轮完成 · 共 {len(entries)} 次回应**\n\n{history}"


def _has_active_children(payload: object) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return False
    active = {"launching", "running", "waiting", "pending", "queued"}
    return any(
        isinstance(child, dict)
        and (child.get("status") in active or child.get("current_task_status") in active)
        for child in payload["data"]
    )


__all__ = ["FeishuRealtimeRuntime"]
