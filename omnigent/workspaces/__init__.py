"""Multi-repository workspace bundle discovery."""

from omnigent.workspaces.manifest import (
    MANIFEST_FILENAME,
    WorkspaceManifest,
    WorkspaceManifestError,
    WorkspaceRepository,
    load_workspace_manifest,
)
from omnigent.workspaces.registry import WorkspaceRegistry

__all__ = [
    "MANIFEST_FILENAME",
    "WorkspaceManifest",
    "WorkspaceManifestError",
    "WorkspaceRegistry",
    "WorkspaceRepository",
    "load_workspace_manifest",
]
