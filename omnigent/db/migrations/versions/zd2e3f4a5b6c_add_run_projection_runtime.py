"""Add provider-neutral Run projection runtime state.

Revision ID: zd2e3f4a5b6c
Revises: zc1d2e3f4a5b
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zd2e3f4a5b6c"
down_revision: str | None = "zc1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("bundle_location", sa.String(512), nullable=True))
        batch.add_column(sa.Column("source_event_id", sa.String(256), nullable=True))
        batch.add_column(sa.Column("auth_scope", sa.String(256), nullable=True))
    op.create_index(
        "uq_runs_external_event",
        "runs",
        ["workspace_id", "auth_scope", "source", "source_event_id"],
        unique=True,
    )

    with op.batch_alter_table("attempts") as batch:
        batch.add_column(sa.Column("failure_message", sa.Text(), nullable=True))

    with op.batch_alter_table("worktree_leases") as batch:
        batch.add_column(sa.Column("run_id", Uuid16(), nullable=True))

    op.create_table(
        "run_projection_events",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("run_id", Uuid16(), nullable=False),
        sa.Column("task_id", Uuid16(), nullable=True),
        sa.Column("attempt_id", Uuid16(), nullable=True),
        sa.Column("session_id", Uuid16(), nullable=True),
        sa.Column("conversation_item_id", Uuid16(), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_event_id", sa.String(256), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "source",
            "source_event_id",
            name="uq_run_projection_events_source",
        ),
    )
    op.create_index(
        "ix_run_projection_events_run",
        "run_projection_events",
        ["workspace_id", "run_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_projection_events_run", table_name="run_projection_events")
    op.drop_table("run_projection_events")
    with op.batch_alter_table("worktree_leases") as batch:
        batch.drop_column("run_id")
    with op.batch_alter_table("attempts") as batch:
        batch.drop_column("failure_message")
    op.drop_index("uq_runs_external_event", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("auth_scope")
        batch.drop_column("source_event_id")
        batch.drop_column("bundle_location")
