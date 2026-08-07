"""Tests for explicit Agent creation of durable product Tasks."""

from __future__ import annotations

import json

import pytest

from omnigent.runner.tool_dispatch import (
    _ALL_LOCAL_TOOLS,
    _NATIVE_RELAY_BUILTIN_TOOLS,
    _WORK_ITEM_TOOLS,
    _execute_work_item_tool,
)
from omnigent.spec.types import AgentSpec
from omnigent.tools.builtins.work_items import SysWorkItemCreateTool
from omnigent.tools.manager import ToolManager


class _Response:
    status_code = 200
    text = ""

    def json(self) -> dict[str, str]:
        return {"id": "task-1", "creator_kind": "agent"}


class _Client:
    def __init__(self) -> None:
        self.call: tuple[str, dict[str, object], dict[str, str]] | None = None

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> _Response:
        self.call = (url, json, headers)
        return _Response()


@pytest.mark.asyncio
async def test_create_posts_filtered_payload_with_agent_provenance() -> None:
    client = _Client()
    output = await _execute_work_item_tool(
        json.dumps(
            {
                "title": "Track the release",
                "description": "Keep this visible",
                "priority": "high",
                "unexpected": "drop me",
            }
        ),
        server_client=client,  # type: ignore[arg-type]
        agent_id="a" * 32,
        conversation_id="c" * 32,
    )

    assert client.call == (
        "/v1/work-items",
        {
            "title": "Track the release",
            "description": "Keep this visible",
            "priority": "high",
        },
        {
            "X-Orvia-Creator-Agent-Id": "a" * 32,
            "X-Orvia-Creator-Session-Id": "c" * 32,
        },
    )
    assert json.loads(output)["creator_kind"] == "agent"


@pytest.mark.asyncio
async def test_create_requires_agent_identity() -> None:
    output = await _execute_work_item_tool(
        '{"title":"Track it"}',
        server_client=_Client(),  # type: ignore[arg-type]
        agent_id=None,
        conversation_id="c" * 32,
    )
    assert "Agent identity" in json.loads(output)["error"]


def test_tool_is_always_registered_and_relayed() -> None:
    names = {
        schema["function"]["name"]
        for schema in ToolManager(AgentSpec(spec_version=1)).get_tool_schemas()
    }
    assert SysWorkItemCreateTool.name() in names
    assert _WORK_ITEM_TOOLS <= _ALL_LOCAL_TOOLS
    assert _WORK_ITEM_TOOLS <= _NATIVE_RELAY_BUILTIN_TOOLS


def test_description_forbids_inferred_tasks() -> None:
    description = SysWorkItemCreateTool.description()
    assert "explicitly asks" in description
    assert "Never turn ordinary discussion" in description


def test_description_explains_assignment_and_coordinator_rules() -> None:
    description = SysWorkItemCreateTool.description()
    assert "assigned to this Agent" in description
    assert "coordinator" in description
