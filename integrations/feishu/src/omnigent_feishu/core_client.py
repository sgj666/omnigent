"""Narrow authenticated HTTP client for provider-neutral Omnigent APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from omnigent_feishu.auth import BearerProvider


class CoreApiError(RuntimeError):
    def __init__(self, status_code: int, detail: object) -> None:
        super().__init__(f"Omnigent API request failed ({status_code})")
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class RunCreateCommand:
    agent_id: str
    workspace_id: str | None
    input: str
    source_event_id: str
    host_id: str | None = None
    execution_mode: str = "auto"

    def payload(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "workspace_id": self.workspace_id,
            "input": self.input,
            "source": "integration:feishu",
            "source_event_id": self.source_event_id,
            "host_id": self.host_id,
            "execution_mode": self.execution_mode,
        }


class CoreClient:
    """Uses only HTTP; provider sender identities never enter request bodies."""

    def __init__(
        self,
        server_url: str,
        bearer: BearerProvider,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._server = server_url.rstrip("/")
        self._bearer = bearer
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = await self._bearer.token()
        response = await self._client.request(
            method,
            f"{self._server}{path}",
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
        if response.status_code == 401:
            token = await self._bearer.refresh()
            response = await self._client.request(
                method,
                f"{self._server}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        if response.is_error:
            try:
                detail = response.json().get("detail", response.json())
            except ValueError:
                detail = {"code": "core_http_error"}
            raise CoreApiError(response.status_code, detail)
        if response.status_code == 204:
            return None
        return response.json()

    async def list_agent_bundles(self, **params: object) -> Any:
        return await self._request("GET", "/v1/agent-bundles", params=params)

    async def get_agent_bundle(self, agent_id: str) -> Any:
        return await self._request("GET", f"/v1/agent-bundles/{agent_id}")

    async def list_workspaces(self) -> Any:
        return await self._request("GET", "/v1/workspaces")

    async def select_workspace(self, workspace_id: str, thread_id: str) -> Any:
        return await self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/select",
            json={"thread_id": thread_id},
        )

    async def create_run(self, command: RunCreateCommand | None = None, **kwargs: Any) -> Any:
        if command is None:
            command = RunCreateCommand(**kwargs)
        return await self._request("POST", "/v1/runs", json=command.payload())

    async def get_run(self, run_id: str) -> Any:
        return await self._request("GET", f"/v1/runs/{run_id}")

    async def get_run_events(self, run_id: str, *, after: str | None = None) -> Any:
        return await self._request(
            "GET", f"/v1/runs/{run_id}/events", params={"after": after} if after else {}
        )

    async def get_run_inspector(self, run_id: str) -> Any:
        return await self._request("GET", f"/v1/runs/{run_id}/inspector")

    async def stop_run(self, run_id: str) -> Any:
        return await self._request("POST", f"/v1/runs/{run_id}/stop")

    async def decide_approval(self, run_id: str, approval_id: str, *, approved: bool) -> Any:
        decision = "approve" if approved else "deny"
        return await self._request("POST", f"/v1/runs/{run_id}/approvals/{approval_id}/{decision}")


OmnigentCoreClient = CoreClient

__all__ = ["CoreApiError", "CoreClient", "OmnigentCoreClient", "RunCreateCommand"]
