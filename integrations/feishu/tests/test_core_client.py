from __future__ import annotations

import httpx
import pytest
from omnigent_feishu.core_client import CoreClient, RunCreateCommand


class Bearer:
    def __init__(self) -> None:
        self.current = "old"

    async def token(self) -> str:
        return self.current

    async def refresh(self) -> str:
        self.current = "new"
        return self.current


@pytest.mark.asyncio
async def test_create_run_is_http_only_refreshes_once_and_has_no_source_actor() -> None:
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers["authorization"] == "Bearer old":
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(201, json={"id": "run"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = CoreClient("https://core.example", Bearer(), client=http)
    result = await client.create_run(
        RunCreateCommand("ag", "ws", "work", "feishu:event", execution_mode="auto")
    )
    body = __import__("json").loads(requests[-1].content)
    assert result["id"] == "run"
    assert len(requests) == 2
    assert body["source"] == "integration:feishu"
    assert "source_actor" not in body
    await http.aclose()
