"""Agent-scoped choices for the Feishu entry surface."""

from __future__ import annotations

from collections.abc import Mapping

DEFAULT_SURFACE_ACTIONS = ("quick_commands", "manage_devices", "switch_workspace")
ALLOWED_SURFACE_ACTIONS = frozenset(
    (*DEFAULT_SURFACE_ACTIONS, "current_run", "stop_session", "help")
)


def surface_profile(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {
            "details_enabled": True,
            "details_base_url": "",
            "actions": list(DEFAULT_SURFACE_ACTIONS),
        }
    return dict(value)


__all__ = ["ALLOWED_SURFACE_ACTIONS", "DEFAULT_SURFACE_ACTIONS", "surface_profile"]
