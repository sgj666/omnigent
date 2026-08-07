"""Add product TaskRun execution history.

Revision ID: zh6c7d8e9f0a
Revises: zg5b6c7d8e9f
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zh6c7d8e9f0a"
down_revision: str | None = "zg5b6c7d8e9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_item_runs",
        sa.Column("workspace_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("work_item_id", Uuid16(), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=True),
        sa.Column("session_id", Uuid16(), nullable=True),
        sa.Column("agent_id", Uuid16(), nullable=False),
        sa.Column("runtime_id", sa.String(128), nullable=False),
        sa.Column("workspace", sa.Text(), nullable=False),
        sa.Column("state", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("trigger", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("retry_of_run_id", Uuid16(), nullable=True),
        sa.Column("queued_at", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=True),
        sa.Column("finished_at", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("failure_retryable", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("artifact_refs", sa.Text(), server_default="[]", nullable=False),
        sa.Column("usage_refs", sa.Text(), server_default="[]", nullable=False),
        sa.CheckConstraint("state IN (1, 2, 3, 4, 5, 6)", name="ck_work_item_runs_state"),
        sa.CheckConstraint("trigger IN (1, 2)", name="ck_work_item_runs_trigger"),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_work_item_runs_task",
        "work_item_runs",
        ["workspace_id", "owner_user_id", "work_item_id", "queued_at", "id"],
    )
    op.create_index(
        "ix_work_item_runs_session",
        "work_item_runs",
        ["workspace_id", "session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_work_item_runs_session", table_name="work_item_runs")
    op.drop_index("ix_work_item_runs_task", table_name="work_item_runs")
    op.drop_table("work_item_runs")
