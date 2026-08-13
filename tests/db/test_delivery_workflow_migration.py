from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

import omnigent.db

_TABLES = {
    "delivery_runs",
    "delivery_planned_tasks",
    "delivery_artifacts",
    "delivery_transitions",
}


def _config(uri: str) -> Config:
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(omnigent.db.__file__).parent / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", uri)
    return config


def test_delivery_workflow_migration_is_workspace_scoped_and_reversible(
    tmp_path: Path,
) -> None:
    uri = f"sqlite:///{tmp_path / 'migration.db'}"
    config = _config(uri)
    command.upgrade(config, "zn2b3c4d5e6f")
    engine = sa.create_engine(uri)
    inspector = sa.inspect(engine)

    assert set(inspector.get_table_names()) >= _TABLES
    assert all(
        inspector.get_pk_constraint(table)["constrained_columns"][0] == "workspace_id"
        for table in _TABLES
    )
    assert all(inspector.get_foreign_keys(table) == [] for table in _TABLES)
    transition_uniques = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("delivery_transitions")
    }
    assert (
        "workspace_id",
        "profile_id",
        "delivery_run_id",
        "idempotency_key",
    ) in transition_uniques
    assert all(
        index["column_names"][0] == "workspace_id"
        for table in _TABLES
        for index in inspector.get_indexes(table)
    )

    engine.dispose()
    command.downgrade(config, "zm1a2b3c4d5e")
    downgraded = sa.create_engine(uri)
    try:
        assert _TABLES.isdisjoint(sa.inspect(downgraded).get_table_names())
    finally:
        downgraded.dispose()
