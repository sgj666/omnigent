"""Discovery and validation of multi-repository workspace bundles."""

from __future__ import annotations

from pathlib import Path

from omnigent.workspaces.manifest import (
    MANIFEST_FILENAME,
    WorkspaceManifest,
    WorkspaceManifestError,
    WorkspaceRepository,
    load_workspace_manifest,
)


class WorkspaceRegistry:
    """Resolve a workspace manifest or first-level Git repositories."""

    def load(self, root: Path | str) -> WorkspaceManifest:
        """Load a manifest-backed workspace and validate each repository root."""
        manifest = load_workspace_manifest(root)
        repositories = self._validate_repository_paths(manifest.root, manifest.repositories)
        return WorkspaceManifest(
            root=manifest.root, repositories=tuple(sorted(repositories, key=lambda repo: repo.id))
        )

    def scan(self, root: Path | str) -> WorkspaceManifest:
        """Discover only immediate child Git roots when no manifest is present."""
        workspace_root = self._workspace_root(root)
        repositories = [
            WorkspaceRepository(id=entry.name, path=entry.name)
            for entry in workspace_root.iterdir()
            if entry.is_dir() and self._is_git_root(entry)
        ]
        return WorkspaceManifest(
            root=workspace_root,
            repositories=tuple(sorted(repositories, key=lambda repo: repo.id)),
        )

    def resolve(self, root: Path | str) -> WorkspaceManifest:
        """Load the manifest when present, otherwise scan direct child Git roots."""
        workspace_root = self._workspace_root(root)
        if (workspace_root / MANIFEST_FILENAME).exists():
            return self.load(workspace_root)
        return self.scan(workspace_root)

    @staticmethod
    def _workspace_root(root: Path | str) -> Path:
        workspace_root = Path(root).resolve()
        if not workspace_root.is_dir():
            raise WorkspaceManifestError(f"workspace root is not a directory: {workspace_root}")
        return workspace_root

    def _validate_repository_paths(
        self, root: Path, repositories: tuple[WorkspaceRepository, ...]
    ) -> list[WorkspaceRepository]:
        resolved_paths: list[Path] = []
        for repository in repositories:
            path = self._repository_path(root, repository.path)
            if not path.is_dir():
                raise WorkspaceManifestError(
                    f"repository path is not a directory: {repository.path}"
                )
            if not self._is_git_root(path):
                raise WorkspaceManifestError(
                    f"repository path is not a Git root: {repository.path}"
                )
            resolved_paths.append(path)
        if len(set(resolved_paths)) != len(resolved_paths):
            raise WorkspaceManifestError("workspace manifest contains duplicate repository paths")
        for path in resolved_paths:
            if any(path in other.parents for other in resolved_paths):
                raise WorkspaceManifestError("workspace manifest contains nested repository paths")
        return list(repositories)

    @staticmethod
    def _repository_path(root: Path, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if (
            candidate.is_absolute()
            or candidate == Path(".")
            or any(part == ".." for part in candidate.parts)
        ):
            raise WorkspaceManifestError(
                f"repository path must stay within the workspace: {relative_path}"
            )
        resolved = (root / candidate).resolve()
        if root != resolved and root not in resolved.parents:
            raise WorkspaceManifestError(
                f"repository path must stay within the workspace: {relative_path}"
            )
        return resolved

    @staticmethod
    def _is_git_root(path: Path) -> bool:
        return (path / ".git").exists()
