"""Tests for discovery of multi-repository workspace bundles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omnigent.workspaces.manifest import WorkspaceManifestError
from omnigent.workspaces.registry import WorkspaceRegistry


def _git_root(parent: Path, name: str) -> Path:
    repository = parent / name
    (repository / ".git").mkdir(parents=True)
    return repository


def _write_manifest(root: Path, projects: list[dict[str, object]]) -> None:
    (root / ".workbench-workspace.json").write_text(
        json.dumps({"expertProjects": projects}), encoding="utf-8"
    )


def test_load_preserves_manifest_metadata_and_orders_repositories(tmp_path: Path) -> None:
    root = tmp_path / "a需求"
    root.mkdir()
    _git_root(root, "web")
    _git_root(root, "api")
    _write_manifest(
        root,
        [
            {
                "id": "web",
                "path": "web",
                "role": "frontend",
                "defaultBranch": "main",
                "writable": False,
                "startupCommands": ["pnpm install", "pnpm dev"],
                "validationCommands": ["pnpm test"],
                "permissions": {"network": "deny"},
            },
            {"id": "api", "path": "api", "role": "backend"},
        ],
    )

    bundle = WorkspaceRegistry().load(root)

    assert bundle.root == root.resolve()
    assert [(repo.id, repo.path) for repo in bundle.repositories] == [
        ("api", "api"),
        ("web", "web"),
    ]
    web = bundle.repositories[1]
    assert web.role == "frontend"
    assert web.default_branch == "main"
    assert web.writable is False
    assert web.startup_commands == ("pnpm install", "pnpm dev")
    assert web.validation_commands == ("pnpm test",)
    assert web.permissions == {"network": "deny"}


def test_scan_falls_back_to_first_level_git_roots_in_stable_order(tmp_path: Path) -> None:
    root = tmp_path / "a需求"
    root.mkdir()
    _git_root(root, "zeta")
    _git_root(root, "alpha")
    _git_root(root / "container", "nested")
    (root / "notes").mkdir()

    bundle = WorkspaceRegistry().scan(root)

    assert [(repo.id, repo.path) for repo in bundle.repositories] == [
        ("alpha", "alpha"),
        ("zeta", "zeta"),
    ]


@pytest.mark.parametrize(
    "project",
    [
        {"id": "escape", "path": "../outside"},
        {"id": "absolute", "path": "/tmp/outside"},
        {"id": "root", "path": "."},
        {"id": "file", "path": "README.md"},
    ],
)
def test_load_rejects_unsafe_or_non_directory_repository_paths(
    tmp_path: Path, project: dict[str, object]
) -> None:
    root = tmp_path / "a需求"
    root.mkdir()
    (root / "README.md").write_text("not a repository", encoding="utf-8")
    _write_manifest(root, [project])

    with pytest.raises(WorkspaceManifestError):
        WorkspaceRegistry().load(root)


def test_load_rejects_nested_repository_entries(tmp_path: Path) -> None:
    root = tmp_path / "a需求"
    root.mkdir()
    parent = _git_root(root, "parent")
    _git_root(parent, "child")
    _write_manifest(
        root,
        [
            {"id": "parent", "path": "parent"},
            {"id": "child", "path": "parent/child"},
        ],
    )

    with pytest.raises(WorkspaceManifestError, match="nested"):
        WorkspaceRegistry().resolve(root)


def test_load_rejects_canonical_path_aliases(tmp_path: Path) -> None:
    root = tmp_path / "a需求"
    root.mkdir()
    _git_root(root, "repo")
    _write_manifest(
        root,
        [
            {"id": "repo", "path": "repo"},
            {"id": "repo-alias", "path": "repo/."},
        ],
    )

    with pytest.raises(WorkspaceManifestError, match="duplicate"):
        WorkspaceRegistry().load(root)
