"""Structure checks for the team-harness persistence migration."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from omnigent.db.utils import clear_engine_cache, get_or_create_engine

_TABLES = {
    "teams",
    "agent_profiles",
    "team_members",
    "workspace_bundles",
    "workspace_repositories",
    "runs",
    "run_tasks",
    "task_dependencies",
    "attempts",
    "harness_events",
    "artifacts",
    "feishu_installations",
    "feishu_notifications",
    "idempotency_keys",
    "thread_workspace_selections",
}


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    """Fresh SQLite database migrated to the current schema head."""
    engine = get_or_create_engine(f"sqlite:///{tmp_path / 'team-harness.db'}")
    try:
        yield engine
    finally:
        clear_engine_cache()


def test_migration_creates_team_harness_tables(db_engine: Engine) -> None:
    """All team-harness state tables exist after a fresh migration."""
    assert set(sa.inspect(db_engine).get_table_names()) >= _TABLES


@pytest.mark.parametrize("table", sorted(_TABLES))
def test_workspace_id_leads_team_harness_primary_keys(db_engine: Engine, table: str) -> None:
    """Each table uses the existing workspace partition as its leading key."""
    primary_key = sa.inspect(db_engine).get_pk_constraint(table)["constrained_columns"]
    assert primary_key and primary_key[0] == "workspace_id"


def test_harness_event_id_is_workspace_unique(db_engine: Engine) -> None:
    """A delivered harness event can be deduplicated by its external event id."""
    inspector = sa.inspect(db_engine)
    event_columns = {column["name"] for column in inspector.get_columns("harness_events")}
    assert {"event_id", "event_type", "payload", "created_at"} <= event_columns
    unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("harness_events")
    }
    index_sets = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("harness_events")
        if index["unique"]
    }
    assert ("workspace_id", "event_id") in unique_sets | index_sets


def test_idempotency_scope_and_key_are_workspace_unique(db_engine: Engine) -> None:
    """Idempotent requests share one durable workspace/scope/key identity."""
    inspector = sa.inspect(db_engine)
    unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("idempotency_keys")
    }
    index_sets = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("idempotency_keys")
        if index["unique"]
    }
    assert ("workspace_id", "scope", "key") in unique_sets | index_sets


def test_feishu_installation_keeps_only_encrypted_secret_material(db_engine: Engine) -> None:
    """The Feishu app secret is persisted as ciphertext, never plaintext."""
    columns = {
        column["name"] for column in sa.inspect(db_engine).get_columns("feishu_installations")
    }
    assert "app_secret_ciphertext" in columns
    assert "app_secret" not in columns
    assert "app_secret_plaintext" not in columns


def test_team_harness_relationships_do_not_add_database_foreign_keys(db_engine: Engine) -> None:
    """Relationships remain application-owned, consistent with Rule R032."""
    inspector = sa.inspect(db_engine)
    assert all(inspector.get_foreign_keys(table) == [] for table in _TABLES)


def test_thread_workspace_selection_is_scoped_by_thread_and_scope(db_engine: Engine) -> None:
    """The selection migration uses workspace/thread/scope as its durable key."""
    assert sa.inspect(db_engine).get_pk_constraint("thread_workspace_selections")[
        "constrained_columns"
    ] == ["workspace_id", "thread_id", "scope"]
