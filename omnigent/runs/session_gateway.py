"""Narrow in-process adapters to the authoritative Session HTTP surface."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runs.service import RootSessionRequest
from omnigent.server.schemas import SessionEventInput


class ASGISessionGateway:
    """Call the mounted Session routes without duplicating their orchestration."""

    def __init__(self, request: Request) -> None:
        self._app = request.app
        self._headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"content-length", "content-type", "host"}
        }

    async def create_root(self, command: RootSessionRequest, actor_id: str) -> str:
        payload: dict[str, Any] = {
            "agent_id": command.agent_id,
            "workspace": command.workspace,
            "host_id": command.host_id,
            "labels": {"run.execution_mode": command.execution_mode},
            "expected_agent_bundle": {
                "version": command.bundle_version,
                "digest": command.bundle_digest,
                "location": command.bundle_location,
            },
        }
        response = await self._post("/v1/sessions", payload)
        session_id = response.get("id") or response.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise OmnigentError(
                "Session create response did not include a session id",
                code=ErrorCode.INTERNAL_ERROR,
            )
        response_version = response.get("agent_bundle_version")
        response_digest = response.get("agent_bundle_digest")
        if response_version is not None and response_version != command.bundle_version:
            await self.cleanup(session_id, actor_id)
            raise OmnigentError(
                "Root Session Agent Bundle version changed during Run creation",
                code=ErrorCode.CONFLICT,
            )
        if response_digest is not None and response_digest != command.bundle_digest:
            await self.cleanup(session_id, actor_id)
            raise OmnigentError(
                "Root Session Agent Bundle digest changed during Run creation",
                code=ErrorCode.CONFLICT,
            )
        return session_id

    async def send_input(
        self,
        session_id: str,
        event: SessionEventInput,
        _actor_id: str,
    ) -> None:
        response = await self._post(
            f"/v1/sessions/{session_id}/events",
            event.model_dump(exclude_none=True),
        )
        if response.get("denied") is True or response.get("queued") is not True:
            raise OmnigentError(
                "Root Session did not accept the initial input",
                code=ErrorCode.CONFLICT,
            )

    async def stop(self, session_id: str) -> None:
        await self._post(
            f"/v1/sessions/{session_id}/events",
            {"type": "stop_session", "data": {}},
        )

    async def cleanup(self, session_id: str, _actor_id: str) -> None:
        """Delete a partially-created Root through Session lifecycle cleanup."""
        await self._delete(f"/v1/sessions/{session_id}?delete_branch=true")

    async def decide_approval(
        self,
        session_id: str,
        approval_id: str,
        decision: str,
    ) -> None:
        await self._post(
            f"/v1/sessions/{session_id}/events",
            {
                "type": "approval",
                "data": {
                    "elicitation_id": approval_id,
                    "action": "accept" if decision == "approve" else "decline",
                },
            },
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self._app),
            base_url="http://omnigent.internal",
            headers=self._headers,
        ) as client:
            response = await client.post(path, json=payload)
        if response.is_success:
            body = response.json()
            return body if isinstance(body, dict) else {}
        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            409: ErrorCode.CONFLICT,
            422: ErrorCode.INVALID_INPUT,
            503: ErrorCode.RUNNER_UNAVAILABLE,
        }.get(response.status_code, ErrorCode.INTERNAL_ERROR)
        message = _error_message(response)
        raise OmnigentError(message, code=code)

    async def _delete(self, path: str) -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self._app),
            base_url="http://omnigent.internal",
            headers=self._headers,
        ) as client:
            response = await client.delete(path)
        if response.is_success or response.status_code == 404:
            return
        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            409: ErrorCode.CONFLICT,
        }.get(response.status_code, ErrorCode.INTERNAL_ERROR)
        raise OmnigentError(_error_message(response), code=code)


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Session gateway failed with HTTP {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
    return f"Session gateway failed with HTTP {response.status_code}"
