"""Read-only Git repository reader for the product Skills inventory.

The reader deliberately has no publish methods. It resolves a remote ref,
clones into a temporary directory, parses ``SKILL.md`` files, and persists a
JSON snapshot keyed by repository identity and commit SHA. Authentication is
accepted only through environment variables and is passed to Git through an
ephemeral askpass helper, never through command-line arguments or repository
URLs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

import yaml

from omnigent.db.utils import now_epoch

_MAX_TEXT_FILE_BYTES = 512 * 1024
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class SkillRepositoryUnavailable(RuntimeError):
    """Raised when the configured Git repository cannot be read."""


@dataclass(frozen=True)
class SkillFile:
    path: str
    content: str
    size: int


@dataclass(frozen=True)
class SkillRecord:
    id: str
    name: str
    description: str
    relative_path: str
    validation_status: Literal["valid", "warning", "error"]
    diagnostics: list[str]
    files: list[SkillFile]

    def summary_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "object": "skill",
            "name": self.name,
            "description": self.description,
            "relative_path": self.relative_path,
            "validation_status": self.validation_status,
            "diagnostics": self.diagnostics,
            "file_count": len(self.files),
        }

    def detail_dict(self) -> dict[str, object]:
        return {**self.summary_dict(), "files": [asdict(file) for file in self.files]}


@dataclass(frozen=True)
class SkillRepositorySource:
    remote_url: str
    ref: str
    skills_path: str
    commit_sha: str | None
    synced_at: int | None
    sync_status: Literal["current", "stale", "unavailable", "unconfigured"]
    error: str | None
    writable: bool = False


@dataclass(frozen=True)
class SkillSnapshot:
    source: SkillRepositorySource
    skills: list[SkillRecord]

    def list_dict(self) -> dict[str, object]:
        return {
            "object": "list",
            "data": [skill.summary_dict() for skill in self.skills],
            "source": asdict(self.source),
        }


class SkillRepositoryReader(Protocol):
    def load(self, *, refresh: bool = False) -> SkillSnapshot:
        """Return the current snapshot, refreshing the remote when requested."""


class GitSkillRepositoryReader:
    """Read and cache a directory of Skills from one Git ref."""

    def __init__(
        self,
        *,
        remote_url: str,
        ref: str,
        skills_path: str,
        cache_dir: Path,
        token_env: str = "ORVIA_SKILLS_GIT_TOKEN",
        username_env: str = "ORVIA_SKILLS_GIT_USERNAME",
    ) -> None:
        self.remote_url = remote_url.strip()
        self.ref = ref.strip() or "main"
        self.skills_path = self._normalize_skills_path(skills_path)
        self.cache_dir = cache_dir
        self.token_env = token_env
        self.username_env = username_env
        identity = f"{self.remote_url}\0{self.ref}\0{self.skills_path}".encode()
        self._repository_key = hashlib.sha256(identity).hexdigest()[:24]
        self._latest: SkillSnapshot | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> GitSkillRepositoryReader:
        cache_value = os.environ.get("ORVIA_SKILLS_CACHE_DIR")
        cache_dir = (
            Path(cache_value).expanduser()
            if cache_value
            else Path.home() / ".omnigent" / "skills-cache"
        )
        return cls(
            remote_url=os.environ.get("ORVIA_SKILLS_GIT_URL", ""),
            ref=os.environ.get("ORVIA_SKILLS_GIT_REF", "main"),
            skills_path=os.environ.get("ORVIA_SKILLS_GIT_PATH", "skills"),
            cache_dir=cache_dir,
        )

    @staticmethod
    def _normalize_skills_path(value: str) -> str:
        path = PurePosixPath(value.strip() or "skills")
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("skills_path must be a relative repository path")
        return path.as_posix()

    @property
    def _repository_cache_dir(self) -> Path:
        return self.cache_dir / self._repository_key

    def load(self, *, refresh: bool = False) -> SkillSnapshot:
        with self._lock:
            if self._latest is not None and not refresh:
                return self._latest
            if not self.remote_url:
                self._latest = self._empty_snapshot(
                    status="unconfigured",
                    error="Skills repository is not configured",
                )
                return self._latest
            try:
                commit_sha = self._remote_head()
                cached = self._read_commit_snapshot(commit_sha)
                snapshot = cached or self._sync_commit(commit_sha)
                self._latest = snapshot
                return snapshot
            except SkillRepositoryUnavailable as exc:
                cached = self._read_latest_snapshot()
                if cached is None:
                    self._latest = self._empty_snapshot(
                        status="unavailable",
                        error=str(exc),
                    )
                else:
                    self._latest = SkillSnapshot(
                        source=SkillRepositorySource(
                            **{
                                **asdict(cached.source),
                                "sync_status": "stale",
                                "error": str(exc),
                            }
                        ),
                        skills=cached.skills,
                    )
                return self._latest

    def _empty_snapshot(
        self,
        *,
        status: Literal["unavailable", "unconfigured"],
        error: str,
    ) -> SkillSnapshot:
        return SkillSnapshot(
            source=SkillRepositorySource(
                remote_url=self.remote_url,
                ref=self.ref,
                skills_path=self.skills_path,
                commit_sha=None,
                synced_at=None,
                sync_status=status,
                error=error,
            ),
            skills=[],
        )

    def _remote_head(self) -> str:
        result = self._run_git(
            "ls-remote",
            "--exit-code",
            self.remote_url,
            self.ref,
            f"refs/heads/{self.ref}",
        )
        for line in result.stdout.splitlines():
            candidate = line.split(maxsplit=1)[0].lower()
            if _COMMIT_RE.fullmatch(candidate):
                return candidate
        raise SkillRepositoryUnavailable(f"Git ref not found: {self.ref}")

    def _sync_commit(self, commit_sha: str) -> SkillSnapshot:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="orvia-skills-", dir=self.cache_dir) as tmp:
            checkout = Path(tmp) / "repository"
            self._run_git(
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                self.ref,
                "--",
                self.remote_url,
                str(checkout),
            )
            actual = self._run_git("-C", str(checkout), "rev-parse", "HEAD").stdout.strip().lower()
            if actual != commit_sha:
                raise SkillRepositoryUnavailable("Git ref changed while the snapshot was loading")
            skills = self._scan_checkout(checkout)
        snapshot = SkillSnapshot(
            source=SkillRepositorySource(
                remote_url=self.remote_url,
                ref=self.ref,
                skills_path=self.skills_path,
                commit_sha=commit_sha,
                synced_at=now_epoch(),
                sync_status="current",
                error=None,
            ),
            skills=skills,
        )
        self._write_snapshot(snapshot)
        return snapshot

    def _scan_checkout(self, checkout: Path) -> list[SkillRecord]:
        root = checkout.joinpath(*PurePosixPath(self.skills_path).parts)
        if not root.is_dir():
            raise SkillRepositoryUnavailable(f"Skills directory not found: {self.skills_path}")
        records: list[SkillRecord] = []
        for manifest in sorted(root.rglob("SKILL.md")):
            if manifest.is_symlink() or not manifest.is_file():
                continue
            records.append(self._parse_skill(checkout, manifest.parent))
        names: dict[str, int] = {}
        for record in records:
            names[record.name] = names.get(record.name, 0) + 1
        deduplicated: list[SkillRecord] = []
        for record in records:
            if names[record.name] <= 1:
                deduplicated.append(record)
                continue
            diagnostics = [*record.diagnostics, f"Duplicate skill name: {record.name}"]
            deduplicated.append(
                SkillRecord(
                    **{
                        **asdict(record),
                        "validation_status": "error",
                        "diagnostics": diagnostics,
                        "files": record.files,
                    }
                )
            )
        return sorted(deduplicated, key=lambda skill: (skill.name.casefold(), skill.relative_path))

    def _parse_skill(self, checkout: Path, skill_dir: Path) -> SkillRecord:
        diagnostics: list[str] = []
        files: list[SkillFile] = []
        for candidate in sorted(skill_dir.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative_file = candidate.relative_to(skill_dir).as_posix()
            size = candidate.stat().st_size
            if size > _MAX_TEXT_FILE_BYTES:
                diagnostics.append(f"Skipped oversized file: {relative_file}")
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                diagnostics.append(f"Skipped non-text file: {relative_file}")
                continue
            files.append(SkillFile(path=relative_file, content=content, size=size))
        manifest_file = next((file for file in files if file.path == "SKILL.md"), None)
        metadata: dict[str, object] = {}
        if manifest_file is None:
            diagnostics.append("SKILL.md could not be read as UTF-8 text")
        else:
            metadata, parse_error = self._frontmatter(manifest_file.content)
            if parse_error:
                diagnostics.append(parse_error)
        fallback_name = skill_dir.name
        raw_name = metadata.get("name")
        name = (
            raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else fallback_name
        )
        if not isinstance(raw_name, str) or not raw_name.strip():
            diagnostics.append("Missing frontmatter field: name")
        raw_description = metadata.get("description")
        description = (
            raw_description.strip()
            if isinstance(raw_description, str) and raw_description.strip()
            else ""
        )
        if not description:
            diagnostics.append("Missing frontmatter field: description")
        relative_path = skill_dir.relative_to(checkout).as_posix()
        status: Literal["valid", "warning", "error"]
        if any(message.startswith(("Missing", "Invalid", "SKILL.md")) for message in diagnostics):
            status = "error"
        elif diagnostics:
            status = "warning"
        else:
            status = "valid"
        return SkillRecord(
            id=hashlib.sha256(relative_path.encode()).hexdigest()[:24],
            name=name,
            description=description,
            relative_path=relative_path,
            validation_status=status,
            diagnostics=diagnostics,
            files=files,
        )

    @staticmethod
    def _frontmatter(content: str) -> tuple[dict[str, object], str | None]:
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, "Invalid SKILL.md frontmatter"
        try:
            end = next(
                index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
            )
        except StopIteration:
            return {}, "Invalid SKILL.md frontmatter"
        try:
            parsed = yaml.safe_load("\n".join(lines[1:end])) or {}
        except yaml.YAMLError:
            return {}, "Invalid SKILL.md frontmatter"
        if not isinstance(parsed, dict):
            return {}, "Invalid SKILL.md frontmatter"
        return {str(key): value for key, value in parsed.items()}, None

    def _write_snapshot(self, snapshot: SkillSnapshot) -> None:
        commit_sha = snapshot.source.commit_sha
        if commit_sha is None:
            return
        payload = {
            "source": asdict(snapshot.source),
            "skills": [skill.detail_dict() for skill in snapshot.skills],
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        commit_dir = self._repository_cache_dir / commit_sha
        commit_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = commit_dir / "snapshot.json"
        latest_path = self._repository_cache_dir / "latest.json"
        for target in (snapshot_path, latest_path):
            temporary = target.with_suffix(".tmp")
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(target)

    def _read_commit_snapshot(self, commit_sha: str) -> SkillSnapshot | None:
        snapshot = self._read_snapshot(self._repository_cache_dir / commit_sha / "snapshot.json")
        if snapshot is None:
            return None
        return SkillSnapshot(
            source=SkillRepositorySource(
                **{
                    **asdict(snapshot.source),
                    "sync_status": "current",
                    "error": None,
                }
            ),
            skills=snapshot.skills,
        )

    def _read_latest_snapshot(self) -> SkillSnapshot | None:
        return self._read_snapshot(self._repository_cache_dir / "latest.json")

    @staticmethod
    def _read_snapshot(path: Path) -> SkillSnapshot | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            source = SkillRepositorySource(**payload["source"])
            skills = [
                SkillRecord(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    relative_path=item["relative_path"],
                    validation_status=item["validation_status"],
                    diagnostics=list(item["diagnostics"]),
                    files=[SkillFile(**file) for file in item["files"]],
                )
                for item in payload["skills"]
            ]
            return SkillSnapshot(source=source, skills=skills)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        askpass_dir: tempfile.TemporaryDirectory[str] | None = None
        token = environment.get(self.token_env)
        if token:
            askpass_dir = tempfile.TemporaryDirectory(prefix="orvia-git-askpass-")
            askpass = Path(askpass_dir.name) / "askpass.sh"
            askpass.write_text(
                "#!/bin/sh\n"
                'case "$1" in\n'
                f'  *Username*) printf "%s\\n" "${{{self.username_env}:-oauth2}}" ;;\n'
                f'  *) printf "%s\\n" "${{{self.token_env}:-}}" ;;\n'
                "esac\n",
                encoding="utf-8",
            )
            askpass.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            environment["GIT_ASKPASS"] = str(askpass)
        try:
            result = subprocess.run(
                ["git", "-c", "credential.helper=", *args],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SkillRepositoryUnavailable("Git repository request failed") from exc
        finally:
            if askpass_dir is not None:
                askpass_dir.cleanup()
        if result.returncode != 0:
            message = self._safe_git_error(result.stderr or result.stdout)
            raise SkillRepositoryUnavailable(message)
        return result

    @staticmethod
    def _safe_git_error(value: str) -> str:
        first_line = next((line.strip() for line in value.splitlines() if line.strip()), "")
        if not first_line:
            return "Git repository request failed"
        sanitized = re.sub(r"(https?://)[^/@\s]+@", r"\1", first_line)
        return sanitized[:300]


def clear_skill_cache(cache_dir: Path) -> None:
    """Test helper for removing a disposable cache directory."""
    shutil.rmtree(cache_dir, ignore_errors=True)
