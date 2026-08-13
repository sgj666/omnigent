"""Database-backed configuration for the Git Skills inventory."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from omnigent.db.db_models import (
    SqlSkillRepositoryConfig,
    current_workspace_id,
)
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.skills.reader import (
    GitSkillRepositoryReader,
    SkillRepositoryReader,
    SkillSnapshot,
)

DEFAULT_SKILLS_REPOSITORY_URL = "http://gitlab.zhuanspirit.com/zz-kf/spec_repo.git"
DEFAULT_SKILLS_REPOSITORY_REF = "spec_repo-feature-6612-2"
DEFAULT_SKILLS_REPOSITORY_PATH = "skills"


class SkillRepositoryConfigurationError(ValueError):
    """The stored Skills repository configuration cannot be used."""


@dataclass(frozen=True)
class StoredSkillRepositoryConfig:
    remote_url: str
    ref: str
    skills_path: str
    username: str | None
    token: str | None = field(repr=False)
    created_at: int
    updated_at: int


@dataclass(frozen=True, repr=False)
class SkillRepositoryConfig:
    remote_url: str
    ref: str
    skills_path: str
    username: str | None
    token: str | None
    updated_at: int


class SqlAlchemySkillRepositoryConfigStore:
    """Persist one strongly typed Skills repository source per workspace."""

    def __init__(self, storage_location: str) -> None:
        self.storage_location = storage_location
        self._session = make_managed_session_maker(get_or_create_engine(storage_location))

    def get(self) -> StoredSkillRepositoryConfig | None:
        with self._session() as session:
            row = session.execute(
                select(SqlSkillRepositoryConfig).where(
                    SqlSkillRepositoryConfig.workspace_id == current_workspace_id()
                )
            ).scalar_one_or_none()
            return _stored(row) if row is not None else None

    def upsert(
        self,
        *,
        remote_url: str,
        ref: str,
        skills_path: str,
        username: str | None,
        token: str | None,
    ) -> StoredSkillRepositoryConfig:
        timestamp = now_epoch()
        with self._session() as session:
            row = session.get(SqlSkillRepositoryConfig, current_workspace_id())
            if row is None:
                row = SqlSkillRepositoryConfig(
                    remote_url=remote_url,
                    ref=ref,
                    skills_path=skills_path,
                    username=username,
                    token=token,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
            else:
                row.remote_url = remote_url
                row.ref = ref
                row.skills_path = skills_path
                row.username = username
                row.token = token
                row.updated_at = timestamp
            session.flush()
            return _stored(row)


def _stored(row: SqlSkillRepositoryConfig) -> StoredSkillRepositoryConfig:
    return StoredSkillRepositoryConfig(
        remote_url=row.remote_url,
        ref=row.ref,
        skills_path=row.skills_path,
        username=row.username,
        token=row.token,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ConfigurableSkillRepositoryReader(SkillRepositoryReader):
    """Select a live Git reader from the current workspace's database row."""

    def __init__(
        self,
        store: SqlAlchemySkillRepositoryConfigStore,
        *,
        initial_settings: Mapping[str, object] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.store = store
        self._cache_dir = cache_dir or _default_cache_dir()
        self._lock = threading.RLock()
        self._readers: dict[int, tuple[tuple[object, ...], GitSkillRepositoryReader]] = {}
        self._seed_if_missing(initial_settings or {})

    def _seed_if_missing(self, settings: Mapping[str, object]) -> None:
        if self.store.get() is not None:
            return
        remote_url = _initial_value(
            "ORVIA_SKILLS_GIT_URL", settings, "url", DEFAULT_SKILLS_REPOSITORY_URL
        )
        ref = _initial_value(
            "ORVIA_SKILLS_GIT_REF", settings, "ref", DEFAULT_SKILLS_REPOSITORY_REF
        )
        skills_path = _initial_value(
            "ORVIA_SKILLS_GIT_PATH", settings, "path", DEFAULT_SKILLS_REPOSITORY_PATH
        )
        username = _initial_value("ORVIA_SKILLS_GIT_USERNAME", settings, "username", "") or None
        token = _initial_value("ORVIA_SKILLS_GIT_TOKEN", settings, "token", "") or None
        normalized = _validate_config(remote_url, ref, skills_path, username, token)
        self.store.upsert(
            remote_url=normalized.remote_url,
            ref=normalized.ref,
            skills_path=normalized.skills_path,
            username=normalized.username,
            token=token,
        )

    def get_config(self) -> SkillRepositoryConfig:
        stored = self.store.get()
        if stored is None:
            raise SkillRepositoryConfigurationError("Skills repository is not configured")
        return SkillRepositoryConfig(
            remote_url=stored.remote_url,
            ref=stored.ref,
            skills_path=stored.skills_path,
            username=stored.username,
            token=stored.token,
            updated_at=stored.updated_at,
        )

    def configure(
        self,
        *,
        remote_url: str,
        ref: str,
        skills_path: str,
        username: str | None,
        token: str | None,
        preserve_token: bool,
    ) -> SkillRepositoryConfig:
        existing = self.get_config()
        effective_token = existing.token if preserve_token else token
        normalized = _validate_config(remote_url, ref, skills_path, username, effective_token)
        self.store.upsert(
            remote_url=normalized.remote_url,
            ref=normalized.ref,
            skills_path=normalized.skills_path,
            username=normalized.username,
            token=normalized.token,
        )
        with self._lock:
            self._readers.pop(current_workspace_id(), None)
        return self.get_config()

    def load(self, *, refresh: bool = False) -> SkillSnapshot:
        config = self.get_config()
        fingerprint = (
            config.remote_url,
            config.ref,
            config.skills_path,
            config.username,
            hashlib.sha256((config.token or "").encode("utf-8")).digest(),
            config.updated_at,
        )
        workspace_id = current_workspace_id()
        with self._lock:
            cached = self._readers.get(workspace_id)
            if cached is None or cached[0] != fingerprint:
                reader = GitSkillRepositoryReader(
                    remote_url=config.remote_url,
                    ref=config.ref,
                    skills_path=config.skills_path,
                    cache_dir=self._cache_dir,
                    username=config.username,
                    token=config.token,
                )
                self._readers[workspace_id] = (fingerprint, reader)
            else:
                reader = cached[1]
        return reader.load(refresh=refresh)


def _initial_value(
    env_name: str,
    settings: Mapping[str, object],
    key: str,
    default: str,
) -> str:
    if env_name in os.environ:
        return os.environ[env_name]
    value = settings.get(key, default)
    return value if isinstance(value, str) else default


def _default_cache_dir() -> Path:
    if configured := os.environ.get("ORVIA_SKILLS_CACHE_DIR"):
        return Path(configured).expanduser()
    return Path.home() / ".omnigent" / "skills-cache"


def _validate_config(
    remote_url: str,
    ref: str,
    skills_path: str,
    username: str | None,
    token: str | None,
) -> SkillRepositoryConfig:
    remote_url = remote_url.strip()
    ref = ref.strip()
    username = username.strip() if username and username.strip() else None
    if not remote_url or len(remote_url) > 2048:
        raise SkillRepositoryConfigurationError("Repository URL is required")
    parsed = urlsplit(remote_url)
    if parsed.username is not None or parsed.password is not None:
        raise SkillRepositoryConfigurationError(
            "Repository URL must not contain embedded credentials"
        )
    if not ref or len(ref) > 256:
        raise SkillRepositoryConfigurationError("Repository ref is required")
    if username is not None and len(username) > 256:
        raise SkillRepositoryConfigurationError("Repository username is too long")
    if token is not None and len(token) > 16 * 1024:
        raise SkillRepositoryConfigurationError("Repository token is too long")
    try:
        normalized_path = GitSkillRepositoryReader._normalize_skills_path(skills_path)
    except ValueError as exc:
        raise SkillRepositoryConfigurationError(str(exc)) from exc
    if len(normalized_path) > 1024:
        raise SkillRepositoryConfigurationError("Skills path is too long")
    return SkillRepositoryConfig(
        remote_url=remote_url,
        ref=ref,
        skills_path=normalized_path,
        username=username,
        token=token,
        updated_at=0,
    )
