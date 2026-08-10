"""Read-only Git-backed Skills inventory tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omnigent.errors import OmnigentError
from omnigent.server.routes.skills import create_skills_router
from omnigent.skills import SkillDraftStore
from omnigent.skills.reader import GitSkillRepositoryReader, SkillRepositoryUnavailable


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_remote(tmp_path: Path) -> tuple[Path, str]:
    work = tmp_path / "work"
    remote = tmp_path / "skills.git"
    work.mkdir()
    _git("init", "-b", "skills-feature", cwd=work)
    _git("config", "user.email", "skills-test@example.com", cwd=work)
    _git("config", "user.name", "Skills Test", cwd=work)
    skill_dir = work / "skills" / "review-helper"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review-helper\ndescription: Review a change safely.\n---\n\n# Review helper\n",
        encoding="utf-8",
    )
    (skill_dir / "references" / "checklist.md").write_text(
        "# Checklist\n\n- Read the diff.\n",
        encoding="utf-8",
    )
    _git("add", ".", cwd=work)
    _git("commit", "-m", "add skill", cwd=work)
    commit_sha = _git("rev-parse", "HEAD", cwd=work)
    _git("clone", "--bare", str(work), str(remote), cwd=tmp_path)
    return remote, commit_sha


def test_reader_scans_skill_files_and_never_changes_remote_refs(tmp_path: Path) -> None:
    remote, commit_sha = _make_remote(tmp_path)
    refs_before = _git("--git-dir", str(remote), "show-ref")
    reader = GitSkillRepositoryReader(
        remote_url=str(remote),
        ref="skills-feature",
        skills_path="skills",
        cache_dir=tmp_path / "cache",
    )

    snapshot = reader.load(refresh=True)

    assert snapshot.source.commit_sha == commit_sha
    assert snapshot.source.sync_status == "current"
    assert snapshot.source.writable is False
    assert len(snapshot.skills) == 1
    skill = snapshot.skills[0]
    assert skill.name == "review-helper"
    assert skill.description == "Review a change safely."
    assert skill.validation_status == "valid"
    assert [file.path for file in skill.files] == ["SKILL.md", "references/checklist.md"]
    assert _git("--git-dir", str(remote), "show-ref") == refs_before


def test_reader_falls_back_to_latest_snapshot_when_remote_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    remote, commit_sha = _make_remote(tmp_path)
    reader = GitSkillRepositoryReader(
        remote_url=str(remote),
        ref="skills-feature",
        skills_path="skills",
        cache_dir=tmp_path / "cache",
    )
    reader.load(refresh=True)

    def unavailable() -> str:
        raise SkillRepositoryUnavailable("offline")

    monkeypatch.setattr(reader, "_remote_head", unavailable)
    snapshot = reader.load(refresh=True)

    assert snapshot.source.commit_sha == commit_sha
    assert snapshot.source.sync_status == "stale"
    assert snapshot.source.error == "offline"
    assert snapshot.skills[0].name == "review-helper"


def test_skills_routes_list_sync_and_return_file_detail(tmp_path: Path) -> None:
    remote, commit_sha = _make_remote(tmp_path)
    reader = GitSkillRepositoryReader(
        remote_url=str(remote),
        ref="skills-feature",
        skills_path="skills",
        cache_dir=tmp_path / "cache",
    )
    app = FastAPI()
    app.include_router(create_skills_router(reader), prefix="/v1")
    client = TestClient(app)

    listed = client.get("/v1/skills")
    assert listed.status_code == 200
    body = listed.json()
    assert body["object"] == "list"
    assert body["source"]["commit_sha"] == commit_sha
    assert body["source"]["writable"] is False
    skill_id = body["data"][0]["id"]
    assert "files" not in body["data"][0]

    detail = client.get(f"/v1/skills/{skill_id}")
    assert detail.status_code == 200
    assert detail.json()["files"][0]["content"].startswith("---\nname: review-helper")

    synced = client.post("/v1/skills/sync")
    assert synced.status_code == 200
    assert synced.json()["source"]["commit_sha"] == commit_sha


def test_skill_draft_validate_dry_run_and_discard_never_change_remote_refs(
    tmp_path: Path,
) -> None:
    remote, commit_sha = _make_remote(tmp_path)
    refs_before = _git("--git-dir", str(remote), "show-ref")
    reader = GitSkillRepositoryReader(
        remote_url=str(remote),
        ref="skills-feature",
        skills_path="skills",
        cache_dir=tmp_path / "cache",
    )
    app = FastAPI()
    app.include_router(
        create_skills_router(reader, draft_store=SkillDraftStore(tmp_path / "drafts")),
        prefix="/v1",
    )
    client = TestClient(app)
    skill = client.get("/v1/skills").json()["data"][0]
    detail = client.get(f"/v1/skills/{skill['id']}").json()
    files = detail["files"]
    files[0]["content"] += "\nUse the checklist before approval.\n"

    saved = client.put(f"/v1/skills/{skill['id']}/draft", json={"files": files})
    assert saved.status_code == 200
    assert saved.json()["draft"]["baseline_sha"] == commit_sha
    assert saved.json()["draft"]["validation"] == {"status": "valid", "diagnostics": []}
    assert saved.json()["publish_enabled"] is False

    loaded = client.get(f"/v1/skills/{skill['id']}/draft")
    assert loaded.status_code == 200
    assert loaded.json()["baseline_current"] is True

    validated = client.post(f"/v1/skills/{skill['id']}/draft/validate")
    assert validated.status_code == 200
    assert validated.json()["validation"]["status"] == "valid"

    dry_run = client.post(f"/v1/skills/{skill['id']}/draft/dry-run")
    assert dry_run.status_code == 200
    assert dry_run.json()["baseline_sha"] == commit_sha
    assert dry_run.json()["changed_files"] == ["SKILL.md"]
    assert "+Use the checklist before approval." in dry_run.json()["diff"]
    assert dry_run.json()["publish_enabled"] is False
    assert _git("--git-dir", str(remote), "show-ref") == refs_before

    discarded = client.delete(f"/v1/skills/{skill['id']}/draft")
    assert discarded.status_code == 204
    assert client.get(f"/v1/skills/{skill['id']}/draft").json()["draft"] is None
    assert _git("--git-dir", str(remote), "show-ref") == refs_before


def test_skill_draft_validation_blocks_secrets_and_dry_run_blocks_ref_drift(
    tmp_path: Path,
) -> None:
    remote, _ = _make_remote(tmp_path)
    reader = GitSkillRepositoryReader(
        remote_url=str(remote),
        ref="skills-feature",
        skills_path="skills",
        cache_dir=tmp_path / "cache",
    )
    app = FastAPI()
    app.include_router(
        create_skills_router(reader, draft_store=SkillDraftStore(tmp_path / "drafts")),
        prefix="/v1",
    )
    client = TestClient(app)
    skill = client.get("/v1/skills").json()["data"][0]
    detail = client.get(f"/v1/skills/{skill['id']}").json()
    detail["files"][0]["content"] += "\ntoken = should-not-be-committed\n"
    saved = client.put(
        f"/v1/skills/{skill['id']}/draft",
        json={"files": detail["files"]},
    )
    assert saved.json()["draft"]["validation"]["status"] == "error"
    assert saved.json()["draft"]["validation"]["diagnostics"] == [
        "Potential secret detected: SKILL.md"
    ]

    work = tmp_path / "work"
    manifest = work / "skills" / "review-helper" / "SKILL.md"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "\nRemote changed.\n",
        encoding="utf-8",
    )
    _git("add", ".", cwd=work)
    _git("commit", "-m", "advance remote", cwd=work)
    _git("push", str(remote), "skills-feature", cwd=work)

    with pytest.raises(OmnigentError, match="changed since this draft") as exc_info:
        client.post(f"/v1/skills/{skill['id']}/draft/dry-run")
    assert exc_info.value.code == "conflict"


def test_unconfigured_reader_returns_actionable_status_without_network(tmp_path: Path) -> None:
    reader = GitSkillRepositoryReader(
        remote_url="",
        ref="main",
        skills_path="skills",
        cache_dir=tmp_path / "cache",
    )

    snapshot = reader.load(refresh=True)

    assert snapshot.skills == []
    assert snapshot.source.sync_status == "unconfigured"
    assert snapshot.source.error == "Skills repository is not configured"


def test_reader_accepts_non_secret_server_settings_with_environment_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORVIA_SKILLS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ORVIA_SKILLS_GIT_REF", "environment-ref")

    reader = GitSkillRepositoryReader.from_environment(
        {
            "url": "https://git.example.test/team/skills.git",
            "ref": "configured-ref",
            "path": "catalog/skills",
            "username": "config-user",
            "token": "config-token",
        }
    )

    assert reader.remote_url == "https://git.example.test/team/skills.git"
    assert reader.ref == "environment-ref"
    assert reader.skills_path == "catalog/skills"
    assert reader.cache_dir == tmp_path / "cache"
    assert reader.token_env == "ORVIA_SKILLS_GIT_TOKEN"
    assert reader._username == "config-user"
    assert reader._token == "config-token"
