"""Minimal create_app smoke for Feishu cutover and Run evaluation wiring."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_create_app_composes_proxy_and_owner_scoped_evaluation(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    paths = {route.path for route in app.routes}
    assert "/v1/agents/{agent_id}/feishu/installations" in paths
    assert "/v1/agents/{agent_id}/feishu/surface/status" in paths
    assert "/v1/runs/{run_id}/evaluation" in paths
    assert "/v1/feishu/installations" not in paths
    assert "/v1/feishu/webhook" not in paths

    run_store = app.state.run_store
    workspace = run_store.create_workspace(root_path=str(tmp_path), repositories=())
    run = run_store.create_run_idempotent(
        auth_scope="user:alice",
        actor_id="alice",
        source="api",
        source_event_id="composition-evaluation",
        agent_id="1" * 32,
        bundle_version=1,
        bundle_digest="2" * 64,
        bundle_location=f"{'1' * 32}/{'2' * 64}",
        workspace_id=workspace.id,
        root_session_id="3" * 32,
    ).run

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://core.test",
    ) as client:
        hidden = await client.get(f"/v1/runs/{run.id}/evaluation")

    assert hidden.status_code == 404
    assert app.state.evaluation_store is not None
    assert app.state.evaluation_service is not None
