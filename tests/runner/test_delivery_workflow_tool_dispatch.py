"""Tests for ZhuanSpec coordinator delivery-workflow tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omnigent.runner.tool_dispatch import (
    _ALL_LOCAL_TOOLS,
    _DELIVERY_WORKFLOW_TOOLS,
    _NATIVE_RELAY_BUILTIN_TOOLS,
    _execute_delivery_workflow_tool,
    build_native_relay_tool_schemas,
)
from omnigent.spec import load
from omnigent.spec.types import AgentSpec, DeliveryWorkflowSpec
from omnigent.tools.manager import ToolManager


class _Response:
    status_code = 200
    text = ""

    def json(self) -> dict[str, str]:
        return {"status": "ok"}


class _Client:
    def __init__(self) -> None:
        self.call: tuple[str, str, dict[str, object] | None, dict[str, str]] | None = None

    async def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        self.call = ("GET", url, None, headers)
        return _Response()

    async def put(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> _Response:
        self.call = ("PUT", url, json, headers)
        return _Response()

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> _Response:
        self.call = ("POST", url, json, headers)
        return _Response()


def _tool_names(spec: AgentSpec) -> set[str]:
    return {
        schema["function"]["name"]
        for schema in ToolManager(spec).get_tool_schemas()
    }


def _coordinator_spec() -> AgentSpec:
    return AgentSpec(
        spec_version=1,
        delivery_workflow=DeliveryWorkflowSpec(
            profile="zhuanspec-development",
            role="coordinator",
        ),
    )


def test_delivery_tools_register_only_for_zhuanspec_coordinator() -> None:
    assert _tool_names(_coordinator_spec()) >= _DELIVERY_WORKFLOW_TOOLS
    assert not (_DELIVERY_WORKFLOW_TOOLS & _tool_names(AgentSpec(spec_version=1)))
    wrong_profile = AgentSpec(
        spec_version=1,
        delivery_workflow=DeliveryWorkflowSpec(profile="other", role="coordinator"),
    )
    wrong_role = AgentSpec(
        spec_version=1,
        delivery_workflow=DeliveryWorkflowSpec(
            profile="zhuanspec-development",
            role="worker",
        ),
    )
    assert not (_DELIVERY_WORKFLOW_TOOLS & _tool_names(wrong_profile))
    assert not (_DELIVERY_WORKFLOW_TOOLS & _tool_names(wrong_role))


def test_native_relay_preserves_the_same_profile_gate() -> None:
    coordinator_names = {
        schema["name"] for schema in build_native_relay_tool_schemas(_coordinator_spec())
    }
    plain_names = {
        schema["name"]
        for schema in build_native_relay_tool_schemas(AgentSpec(spec_version=1))
    }
    assert coordinator_names >= _DELIVERY_WORKFLOW_TOOLS
    assert not (_DELIVERY_WORKFLOW_TOOLS & plain_names)
    assert _ALL_LOCAL_TOOLS >= _DELIVERY_WORKFLOW_TOOLS
    assert _NATIVE_RELAY_BUILTIN_TOOLS >= _DELIVERY_WORKFLOW_TOOLS


@pytest.mark.parametrize("example", ["polly", "debby"])
def test_existing_multi_agent_examples_do_not_gain_delivery_tools(example: str) -> None:
    example_dir = Path(__file__).resolve().parents[2] / "examples" / example

    assert load(example_dir).delivery_workflow is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_request"),
    [
        (
            "delivery_get_state",
            {},
            ("GET", "/v1/delivery-workflow", None),
        ),
        (
            "delivery_put_plan",
            {"expected_version": 0, "tasks": [], "ignored": True},
            (
                "PUT",
                "/v1/delivery-workflow/plan",
                {"expected_version": 0, "tasks": []},
            ),
        ),
        (
            "delivery_register_artifact",
            {
                "kind": "design",
                "location": "zhuanspec/design.md",
                "content_sha256": "b" * 64,
            },
            (
                "POST",
                "/v1/delivery-workflow/artifacts",
                {
                    "kind": "design",
                    "location": "zhuanspec/design.md",
                    "content_sha256": "b" * 64,
                },
            ),
        ),
        (
            "delivery_transition",
            {
                "expected_phase": "intake",
                "expected_version": 1,
                "to_phase": "design",
                "to_status": "active",
                "idempotency_key": "move-to-design",
                "evidence_refs": [],
            },
            (
                "POST",
                "/v1/delivery-workflow/transitions",
                {
                    "expected_phase": "intake",
                    "expected_version": 1,
                    "to_phase": "design",
                    "to_status": "active",
                    "idempotency_key": "move-to-design",
                    "evidence_refs": [],
                },
            ),
        ),
    ],
)
async def test_delivery_tool_proxies_locked_run_api(
    tool_name: str,
    arguments: dict[str, object],
    expected_request: tuple[str, str, dict[str, object] | None],
) -> None:
    client = _Client()

    output = await _execute_delivery_workflow_tool(
        tool_name,
        arguments,
        server_client=client,  # type: ignore[arg-type]
        agent_spec=_coordinator_spec(),
        agent_id="agent-1",
        conversation_id="session-1",
    )

    assert client.call == (
        *expected_request,
        {
            "X-Orvia-Workflow-Agent-Id": "agent-1",
            "X-Orvia-Workflow-Session-Id": "session-1",
        },
    )
    assert json.loads(output) == {"status": "ok"}


@pytest.mark.asyncio
async def test_delivery_dispatch_rejects_worker_spec_without_request() -> None:
    client = _Client()
    output = await _execute_delivery_workflow_tool(
        "delivery_get_state",
        {},
        server_client=client,  # type: ignore[arg-type]
        agent_spec=AgentSpec(spec_version=1),
        agent_id="worker-1",
        conversation_id="worker-session-1",
    )

    assert "only available to the coordinator" in json.loads(output)["error"]
    assert client.call is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_id", "conversation_id", "expected_error"),
    [
        (None, "session-1", "Agent identity"),
        ("agent-1", None, "Session identity"),
    ],
)
async def test_delivery_dispatch_requires_agent_and_session_provenance(
    agent_id: str | None,
    conversation_id: str | None,
    expected_error: str,
) -> None:
    client = _Client()
    output = await _execute_delivery_workflow_tool(
        "delivery_get_state",
        {},
        server_client=client,  # type: ignore[arg-type]
        agent_spec=_coordinator_spec(),
        agent_id=agent_id,
        conversation_id=conversation_id,
    )

    assert expected_error in json.loads(output)["error"]
    assert client.call is None
