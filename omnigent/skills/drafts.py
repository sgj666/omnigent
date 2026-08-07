"""Owner-scoped local drafts for Git-backed Skills.

Drafts are deliberately separate from a Git checkout. Saving, validating, and
generating a dry-run diff only touch this local JSON store; this module has no
Git publisher and cannot mutate a remote repository.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml

from omnigent.db.utils import now_epoch
from omnigent.skills.reader import SkillFile, SkillRecord

_MAX_FILE_BYTES = 512 * 1024
_MAX_DRAFT_BYTES = 2 * 1024 * 1024
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_SENSITIVE_RE = re.compile(
    r"(?im)^\s*(?:api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*['\"]?\S+"
)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


@dataclass(frozen=True)
class SkillDraftValidation:
    status: Literal["valid", "warning", "error"]
    diagnostics: list[str]


@dataclass(frozen=True)
class SkillDraft:
    skill_id: str
    baseline_sha: str
    relative_path: str
    updated_at: int
    files: list[SkillFile]
    validation: SkillDraftValidation

    def to_dict(self) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "baseline_sha": self.baseline_sha,
            "relative_path": self.relative_path,
            "updated_at": self.updated_at,
            "files": [asdict(file) for file in self.files],
            "validation": asdict(self.validation),
        }


def _normalize_path(value: str) -> str | None:
    path = PurePosixPath(value.strip())
    if not value.strip() or path.is_absolute() or ".." in path.parts:
        return None
    normalized = path.as_posix()
    return None if normalized in {"", "."} else normalized


def validate_skill_draft(files: list[SkillFile]) -> SkillDraftValidation:
    """Validate a complete local Skill draft without writing any files."""
    errors: list[str] = []
    warnings: list[str] = []
    paths: set[str] = set()
    total_bytes = 0
    normalized_files: dict[str, SkillFile] = {}

    for file in files:
        path = _normalize_path(file.path)
        if path is None:
            errors.append(f"Invalid file path: {file.path}")
            continue
        if path in paths:
            errors.append(f"Duplicate file path: {path}")
            continue
        paths.add(path)
        size = len(file.content.encode("utf-8"))
        total_bytes += size
        if size > _MAX_FILE_BYTES:
            errors.append(f"File exceeds {_MAX_FILE_BYTES} bytes: {path}")
        if _SENSITIVE_RE.search(file.content) or _PRIVATE_KEY_RE.search(file.content):
            errors.append(f"Potential secret detected: {path}")
        normalized_files[path] = SkillFile(path=path, content=file.content, size=size)

    if total_bytes > _MAX_DRAFT_BYTES:
        errors.append(f"Draft exceeds {_MAX_DRAFT_BYTES} bytes")

    manifest = normalized_files.get("SKILL.md")
    if manifest is None:
        errors.append("Missing required file: SKILL.md")
    else:
        lines = manifest.content.splitlines()
        if not lines or lines[0].strip() != "---":
            errors.append("Invalid SKILL.md frontmatter")
        else:
            try:
                end = next(
                    index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
                )
                metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
            except (StopIteration, yaml.YAMLError):
                metadata = None
            if not isinstance(metadata, dict):
                errors.append("Invalid SKILL.md frontmatter")
            else:
                if not isinstance(metadata.get("name"), str) or not metadata["name"].strip():
                    errors.append("Missing frontmatter field: name")
                if (
                    not isinstance(metadata.get("description"), str)
                    or not metadata["description"].strip()
                ):
                    errors.append("Missing frontmatter field: description")

    for path, file in normalized_files.items():
        if not path.lower().endswith(".md"):
            continue
        parent = PurePosixPath(path).parent
        for raw_target in _MARKDOWN_LINK_RE.findall(file.content):
            target = raw_target.strip().split("#", 1)[0]
            if not target or target.startswith(
                ("http://", "https://", "mailto:", "skill://", "/")
            ):
                continue
            resolved = _normalize_path((parent / target).as_posix())
            if resolved is None or resolved not in normalized_files:
                errors.append(f"Missing referenced file from {path}: {raw_target.strip()}")

    diagnostics = [*dict.fromkeys(errors), *dict.fromkeys(warnings)]
    status: Literal["valid", "warning", "error"]
    if errors:
        status = "error"
    elif warnings:
        status = "warning"
    else:
        status = "valid"
    return SkillDraftValidation(status=status, diagnostics=diagnostics)


class SkillDraftStore:
    """Persist local Skill drafts in an owner-scoped directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def from_environment(cls) -> SkillDraftStore:
        import os

        value = os.environ.get("ORVIA_SKILLS_DRAFT_DIR")
        root = Path(value).expanduser() if value else Path.home() / ".omnigent" / "skills-drafts"
        return cls(root)

    @staticmethod
    def _owner_key(owner_user_id: str | None) -> str:
        identity = owner_user_id if owner_user_id is not None else "__local__"
        return hashlib.sha256(identity.encode()).hexdigest()[:24]

    def _path(self, owner_user_id: str | None, skill_id: str) -> Path:
        safe_skill_id = hashlib.sha256(skill_id.encode()).hexdigest()[:24]
        return self.root / self._owner_key(owner_user_id) / f"{safe_skill_id}.json"

    def get(self, owner_user_id: str | None, skill_id: str) -> SkillDraft | None:
        path = self._path(owner_user_id, skill_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            files = [SkillFile(**item) for item in payload["files"]]
            return SkillDraft(
                skill_id=payload["skill_id"],
                baseline_sha=payload["baseline_sha"],
                relative_path=payload["relative_path"],
                updated_at=int(payload["updated_at"]),
                files=files,
                validation=validate_skill_draft(files),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(
        self,
        owner_user_id: str | None,
        skill: SkillRecord,
        baseline_sha: str,
        files: list[SkillFile],
    ) -> SkillDraft:
        draft = SkillDraft(
            skill_id=skill.id,
            baseline_sha=baseline_sha,
            relative_path=skill.relative_path,
            updated_at=now_epoch(),
            files=files,
            validation=validate_skill_draft(files),
        )
        path = self._path(owner_user_id, skill.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(draft.to_dict(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)
        return draft

    def delete(self, owner_user_id: str | None, skill_id: str) -> bool:
        path = self._path(owner_user_id, skill_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True


def build_skill_dry_run(skill: SkillRecord, draft: SkillDraft) -> dict[str, object]:
    """Return a unified diff against the immutable baseline snapshot."""
    baseline = {file.path: file.content for file in skill.files}
    proposed = {file.path: file.content for file in draft.files}
    changed_files: list[str] = []
    chunks: list[str] = []
    for path in sorted(baseline.keys() | proposed.keys()):
        before = baseline.get(path, "")
        after = proposed.get(path, "")
        if before == after:
            continue
        changed_files.append(path)
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{skill.relative_path}/{path}",
                tofile=f"b/{skill.relative_path}/{path}",
            )
        )
    return {
        "baseline_sha": draft.baseline_sha,
        "relative_path": skill.relative_path,
        "changed_files": changed_files,
        "diff": "".join(chunks),
        "validation": asdict(draft.validation),
        "publish_enabled": False,
    }
