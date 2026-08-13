"""Database-backed Skills repository configuration tests."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from omnigent.db.db_models import workspace_scope
from omnigent.db.utils import get_or_create_engine
from omnigent.skills.config import (
    ConfigurableSkillRepositoryReader,
    SqlAlchemySkillRepositoryConfigStore,
)


def _database_uri(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'skills-config.db'}"


def test_repository_config_is_self_contained_persistent_and_workspace_scoped(
    tmp_path: Path,
) -> None:
    database_uri = _database_uri(tmp_path)
    store = SqlAlchemySkillRepositoryConfigStore(database_uri)

    assert store.get() is None
    store.upsert(
        remote_url="https://git.example.test/team/skills.git",
        ref="release",
        skills_path="catalog/skills",
        username="oauth2",
        token="plain-token-marker",
    )

    restored = SqlAlchemySkillRepositoryConfigStore(database_uri).get()
    assert restored is not None
    assert restored.remote_url == "https://git.example.test/team/skills.git"
    assert restored.ref == "release"
    assert restored.skills_path == "catalog/skills"
    assert restored.username == "oauth2"
    assert restored.token == "plain-token-marker"
    assert "plain-token-marker" not in repr(restored)
    with get_or_create_engine(database_uri).connect() as connection:
        persisted_token = connection.execute(
            text("SELECT token FROM skill_repository_configs WHERE workspace_id = 0")
        ).scalar_one()
    assert persisted_token == "plain-token-marker"

    with workspace_scope(17):
        assert SqlAlchemySkillRepositoryConfigStore(database_uri).get() is None
        store.upsert(
            remote_url="https://git.example.test/other/skills.git",
            ref="main",
            skills_path="skills",
            username=None,
            token=None,
        )
        assert store.get().remote_url == "https://git.example.test/other/skills.git"

    assert store.get().remote_url == "https://git.example.test/team/skills.git"


def test_configurable_reader_seeds_defaults_and_preserves_or_replaces_token(
    tmp_path: Path,
) -> None:
    database_uri = _database_uri(tmp_path)
    store = SqlAlchemySkillRepositoryConfigStore(database_uri)
    reader = ConfigurableSkillRepositoryReader(
        store,
        cache_dir=tmp_path / "cache",
        initial_settings={
            "url": "https://git.example.test/default/skills.git",
            "ref": "default-ref",
            "path": "skills",
            "username": "default-user",
            "token": "initial-token",
        },
    )

    seeded = reader.get_config()
    assert seeded.remote_url == "https://git.example.test/default/skills.git"
    assert seeded.ref == "default-ref"
    assert seeded.username == "default-user"
    assert seeded.token == "initial-token"

    reader.configure(
        remote_url="https://git.example.test/next/skills.git",
        ref="next-ref",
        skills_path="agent-skills",
        username="next-user",
        token=None,
        preserve_token=True,
    )
    assert reader.get_config().token == "initial-token"

    reader.configure(
        remote_url="https://git.example.test/next/skills.git",
        ref="next-ref",
        skills_path="agent-skills",
        username="next-user",
        token="replacement-token",
        preserve_token=False,
    )
    assert reader.get_config().token == "replacement-token"

    restarted = ConfigurableSkillRepositoryReader(
        SqlAlchemySkillRepositoryConfigStore(database_uri),
        cache_dir=tmp_path / "cache",
        initial_settings={"url": "https://ignored.example.test/skills.git"},
    )
    assert restarted.get_config().remote_url == "https://git.example.test/next/skills.git"
    assert restarted.get_config().token == "replacement-token"

    with get_or_create_engine(database_uri).connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(skill_repository_configs)"))
        }
    assert "token" in columns
    assert "token_ciphertext" not in columns
