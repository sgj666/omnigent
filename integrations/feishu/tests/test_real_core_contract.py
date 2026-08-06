"""Cross-process contract between the Feishu client and Core Sessions."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request
from omnigent_feishu.auth import StaticBearerProvider
from omnigent_feishu.core_client import CoreClient, SessionCreateCommand


def _core_app() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/sessions", status_code=201)
    async def create_session(request: Request) -> dict[str, object]:
        assert request.headers["authorization"] == "Bearer alice"
        body = await request.json()
        assert body == {
            "agent_id": "1" * 32,
            "workspace": "/Users/alice/projects",
            "host_id": "host-1",
        }
        return {"id": "session-root", "status": "launching"}

    @app.post("/v1/sessions/session-root/events")
    async def send_event(request: Request) -> dict[str, object]:
        assert await request.json() == {
            "type": "message",
            "data": {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
        }
        return {"accepted": True}

    return app


@pytest.mark.asyncio
async def test_feishu_creates_and_inputs_a_real_core_session() -> None:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(_core_app()), base_url="http://core")
    client = CoreClient("http://core", StaticBearerProvider("alice"), client=http)

    created = await client.create_session(
        SessionCreateCommand("1" * 32, "/Users/alice/projects", "host-1")
    )
    accepted = await client.send_session_input(str(created["id"]), "hello")

    assert created["id"] == "session-root"
    assert accepted == {"accepted": True}
    await http.aclose()
