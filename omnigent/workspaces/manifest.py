"""Workspace manifest parsing for multi-repository bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = ".workbench-workspace.json"


class WorkspaceManifestError(ValueError):
    """Raised when a workspace manifest cannot safely describe a bundle."""


@dataclass(frozen=True)
class WorkspaceRepository:
    """One repository declared by a workspace manifest."""

    id: str
    path: str
    role: str | None = None
    default_branch: str | None = None
    writable: bool = True
    startup_commands: tuple[str, ...] = ()
    validation_commands: tuple[str, ...] = ()
    permissions: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceManifest:
    """The repository declarations read from one workspace manifest."""

    root: Path
    repositories: tuple[WorkspaceRepository, ...]


def load_workspace_manifest(root: Path | str) -> WorkspaceManifest:
    """Read and validate ``.workbench-workspace.json`` below *root*."""
    workspace_root = Path(root).resolve()
    manifest_path = workspace_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise WorkspaceManifestError(f"workspace manifest not found: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceManifestError(f"invalid workspace manifest: {manifest_path}") from exc
    if not isinstance(payload, dict):
        raise WorkspaceManifestError("workspace manifest must be a JSON object")
    projects = payload.get("expertProjects")
    if not isinstance(projects, list):
        raise WorkspaceManifestError("workspace manifest expertProjects must be a list")

    repositories = tuple(
        _parse_repository(project, index) for index, project in enumerate(projects)
    )
    _validate_unique_repositories(repositories)
    return WorkspaceManifest(root=workspace_root, repositories=repositories)


def _parse_repository(project: object, index: int) -> WorkspaceRepository:
    if not isinstance(project, dict):
        raise WorkspaceManifestError(f"expertProjects[{index}] must be an object")

    path = _required_string(project, "path", index)
    repository_id = _optional_string(project, "id", index) or _optional_string(
        project, "name", index
    )
    if repository_id is None:
        repository_id = Path(path).name
    return WorkspaceRepository(
        id=repository_id,
        path=path,
        role=_optional_string(project, "role", index),
        default_branch=_optional_string(project, "defaultBranch", index)
        or _optional_string(project, "default_branch", index),
        writable=_optional_bool(project, "writable", index, default=True),
        startup_commands=_commands(project, "startupCommands", "startup_commands", index),
        validation_commands=_commands(project, "validationCommands", "validation_commands", index),
        permissions=_permissions(project, index),
    )


def _required_string(project: dict[str, Any], field_name: str, index: int) -> str:
    value = project.get(field_name)
    if not isinstance(value, str) or not value:
        raise WorkspaceManifestError(
            f"expertProjects[{index}].{field_name} must be a non-empty string"
        )
    return value


def _optional_string(project: dict[str, Any], field_name: str, index: int) -> str | None:
    value = project.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise WorkspaceManifestError(
            f"expertProjects[{index}].{field_name} must be a non-empty string"
        )
    return value


def _optional_bool(project: dict[str, Any], field_name: str, index: int, *, default: bool) -> bool:
    value = project.get(field_name, default)
    if not isinstance(value, bool):
        raise WorkspaceManifestError(f"expertProjects[{index}].{field_name} must be a boolean")
    return value


def _commands(
    project: dict[str, Any], camel_name: str, snake_name: str, index: int
) -> tuple[str, ...]:
    value = project.get(camel_name, project.get(snake_name, []))
    if not isinstance(value, list) or not all(
        isinstance(command, str) and command for command in value
    ):
        raise WorkspaceManifestError(
            f"expertProjects[{index}].{camel_name} must be a list of strings"
        )
    return tuple(value)


def _permissions(project: dict[str, Any], index: int) -> dict[str, object]:
    value = project.get("permissions", {})
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise WorkspaceManifestError(f"expertProjects[{index}].permissions must be an object")
    return dict(value)


def _validate_unique_repositories(repositories: tuple[WorkspaceRepository, ...]) -> None:
    ids = [repository.id for repository in repositories]
    paths = [repository.path for repository in repositories]
    if len(set(ids)) != len(ids):
        raise WorkspaceManifestError("workspace manifest contains duplicate repository ids")
    if len(set(paths)) != len(paths):
        raise WorkspaceManifestError("workspace manifest contains duplicate repository paths")
