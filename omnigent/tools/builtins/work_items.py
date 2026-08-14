"""Built-in tool for explicitly creating a durable Orvia Task."""

from __future__ import annotations

from typing import Any

from omnigent.tools.base import Tool


class SysWorkItemCreateTool(Tool):
    """Create a Task through the authenticated Orvia server."""

    @classmethod
    def name(cls) -> str:
        return "sys_work_item_create"

    @classmethod
    def description(cls) -> str:
        return (
            "Create a durable Task on the user's Orvia Task board. Use this only "
            "when the user explicitly asks to create a task, add work to the board, "
            "or track/follow up work durably. Never turn ordinary discussion, "
            "brainstorming, or a one-off request into a Task without an explicit "
            "request. In a single-Agent session, the Task is automatically assigned "
            "to this Agent. In a multi-Agent session, only the coordinator may use "
            "this tool and may assign the Task to an Agent. Worker Agents must return "
            "their result to the coordinator instead of creating Tasks themselves."
        )

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name(),
                "description": self.description(),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "state": {"type": "string", "enum": ["backlog", "todo"]},
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "urgent"],
                        },
                        "project_id": {"type": "string"},
                        "assignee_agent_id": {"type": "string"},
                        "assignee_worker_name": {"type": "string"},
                        "parent_work_item_id": {"type": "string"},
                        "task_kind": {
                            "type": "string",
                            "enum": ["general", "requirement", "delivery"],
                        },
                        "due_at": {"type": "integer"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
            },
        }
