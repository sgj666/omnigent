"""Coordinator tools for the ZhuanSpec delivery workflow."""

from __future__ import annotations

from typing import Any

from omnigent.tools.base import Tool


def _schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_EXPECTED_VERSION = {
    "type": "integer",
    "minimum": 0,
    "description": "The current delivery workflow version used for optimistic concurrency.",
}


class DeliveryGetStateTool(Tool):
    """Read the current profile-scoped delivery snapshot."""

    @classmethod
    def name(cls) -> str:
        return "delivery_get_state"

    @classmethod
    def description(cls) -> str:
        return (
            "Read the plan, artifacts, transitions, phase, status, and version "
            "for a Runtime Run."
        )

    def get_schema(self) -> dict[str, Any]:
        return _schema(self.name(), self.description(), {}, [])


class DeliveryPutPlanTool(Tool):
    """Create or replace the delivery plan with version checking."""

    @classmethod
    def name(cls) -> str:
        return "delivery_put_plan"

    @classmethod
    def description(cls) -> str:
        return (
            "Create or replace the delivery plan. Use expected_version=0 only "
            "for initial creation; "
            "use the snapshot version for later replacements."
        )

    def get_schema(self) -> dict[str, Any]:
        task = {
            "type": "object",
            "properties": {
                "task_key": {"type": "string"},
                "title": {"type": "string"},
                "owner_role": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "task_kind": {
                    "type": "string",
                    "enum": ["requirement", "delivery"],
                    "default": "delivery",
                },
                "parent_task_key": {"type": ["string", "null"]},
                "depends_on": {"type": "array", "items": {"type": "string"}, "default": []},
                "artifact_requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
            },
            "required": ["task_key", "title"],
            "additionalProperties": False,
        }
        return _schema(
            self.name(),
            self.description(),
            {
                "expected_version": _EXPECTED_VERSION,
                "tasks": {"type": "array", "items": task},
            },
            ["expected_version", "tasks"],
        )


class DeliveryRegisterArtifactTool(Tool):
    """Register a durable artifact as delivery evidence."""

    @classmethod
    def name(cls) -> str:
        return "delivery_register_artifact"

    @classmethod
    def description(cls) -> str:
        return "Register an artifact produced by a planned task so later transitions can cite it."

    def get_schema(self) -> dict[str, Any]:
        return _schema(
            self.name(),
            self.description(),
            {
                "kind": {"type": "string"},
                "location": {"type": "string"},
                "content_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-fA-F]{64}$",
                },
                "planned_task_id": {
                    "type": ["string", "null"],
                    "description": "Optional planned-task UUID from the current snapshot.",
                },
                "metadata": {"type": "object", "additionalProperties": True},
            },
            ["kind", "location", "content_sha256"],
        )


class DeliveryTransitionTool(Tool):
    """Apply an evidence-backed delivery state transition."""

    @classmethod
    def name(cls) -> str:
        return "delivery_transition"

    @classmethod
    def description(cls) -> str:
        return (
            "Advance, block, or resume the delivery workflow using the current phase/version and "
            "registered artifact ids as evidence."
        )

    def get_schema(self) -> dict[str, Any]:
        return _schema(
            self.name(),
            self.description(),
            {
                "expected_phase": {"type": "string"},
                "expected_version": _EXPECTED_VERSION,
                "to_phase": {"type": "string"},
                "to_status": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
            [
                "expected_phase",
                "expected_version",
                "to_phase",
                "to_status",
                "idempotency_key",
                "evidence_refs",
            ],
        )


class DeliveryReadyTasksTool(Tool):
    @classmethod
    def name(cls) -> str:
        return "delivery_get_ready_tasks"

    @classmethod
    def description(cls) -> str:
        return (
            "List assigned delivery Tasks whose dependencies are complete "
            "and may be dispatched."
        )

    def get_schema(self) -> dict[str, Any]:
        return _schema(self.name(), self.description(), {}, [])


class DeliveryAssignTaskTool(Tool):
    @classmethod
    def name(cls) -> str:
        return "delivery_assign_task"

    @classmethod
    def description(cls) -> str:
        return "Assign or unassign one board-backed delivery Task to an internal Worker."

    def get_schema(self) -> dict[str, Any]:
        return _schema(
            self.name(),
            self.description(),
            {
                "task_key": {"type": "string"},
                "expected_version": {"type": "integer", "minimum": 1},
                "worker_name": {"type": ["string", "null"]},
            },
            ["task_key", "expected_version", "worker_name"],
        )

DELIVERY_WORKFLOW_TOOLS = (
    DeliveryGetStateTool,
    DeliveryPutPlanTool,
    DeliveryRegisterArtifactTool,
    DeliveryTransitionTool,
    DeliveryReadyTasksTool,
    DeliveryAssignTaskTool,
)
