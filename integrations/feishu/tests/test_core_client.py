from __future__ import annotations

import httpx
import pytest
from omnigent_feishu.core_client import CoreClient, SessionCreateCommand


class Bearer:
    def __init__(self) -> None:
        self.current = "old"

    async def token(self) -> str:
        return self.current

    async def refresh(self) -> str:
        self.current = "new"
        return self.current


@pytest.mark.asyncio
async def test_create_session_posts_to_supported_sessions_api() -> None:
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers["authorization"] == "Bearer old":
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(201, json={"id": "run"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = CoreClient("https://core.example", Bearer(), client=http)
    result = await client.create_session(SessionCreateCommand("ag", "/workspace", "host-1"))
    body = __import__("json").loads(requests[-1].content)
    assert result["id"] == "run"
    assert len(requests) == 2
    assert requests[-1].url.path == "/v1/sessions"
    assert body == {"agent_id": "ag", "workspace": "/workspace", "host_id": "host-1"}
    await http.aclose()
