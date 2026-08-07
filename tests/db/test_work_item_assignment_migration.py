"""Data migration coverage for Agent-created Task assignment."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

import omnigent.db


def _config(uri: str) -> Config:
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(omnigent.db.__file__).parent / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", uri)
    return config


def test_backfills_only_unassigned_agent_created_tasks(tmp_path: Path) -> None:
    uri = f"sqlite:///{tmp_path / 'tasks.db'}"
    config = _config(uri)
    command.upgrade(config, "zk9f0a1b2c3d")
    engine = sa.create_engine(uri)
    creator_id = bytes.fromhex("a" * 32)
    explicit_assignee_id = bytes.fromhex("b" * 32)
    rows = [
        (bytes.fromhex("1" * 32), "Agent unassigned", 2, creator_id, None),
        (
            bytes.fromhex("2" * 32),
            "Agent delegated",
            2,
            creator_id,
            explicit_assignee_id,
        ),
        (bytes.fromhex("3" * 32), "User unassigned", 1, None, None),
    ]
    with engine.begin() as connection:
        for task_id, title, creator_kind, created_by, assignee in rows:
            connection.execute(
                sa.text(
                    "INSERT INTO work_items "
                    "(id, title, created_at, creator_kind, created_by_agent_id, "
                    "assignee_agent_id) VALUES "
                    "(:id, :title, 1, :creator_kind, :created_by, :assignee)"
                ),
                {
                    "id": task_id,
                    "title": title,
                    "creator_kind": creator_kind,
                    "created_by": created_by,
                    "assignee": assignee,
                },
            )

    command.upgrade(config, "zl0a1b2c3d4e")

    with engine.connect() as connection:
        assignments = dict(
            connection.execute(
                sa.text("SELECT title, assignee_agent_id FROM work_items ORDER BY title")
            ).all()
        )
    engine.dispose()

    assert bytes(assignments["Agent unassigned"]) == creator_id
    assert bytes(assignments["Agent delegated"]) == explicit_assignee_id
    assert assignments["User unassigned"] is None
