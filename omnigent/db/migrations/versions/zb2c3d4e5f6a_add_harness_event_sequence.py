"""Add durable ordering to harness events.

Revision ID: zb2c3d4e5f6a
Revises: za1b2c3d4e5f
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "zb2c3d4e5f6a"
down_revision: str | None = "zb1c2d3e4f5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a workspace-local ordering value for deterministic replay."""

    op.add_column(
        "harness_events",
        sa.Column("sequence", sa.BigInteger(), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT workspace_id, id FROM harness_events ORDER BY workspace_id, created_at, id"
        )
    )
    workspace_id: int | None = None
    next_sequence = 0
    for row in rows:
        if row.workspace_id != workspace_id:
            workspace_id = row.workspace_id
            next_sequence = 1
        else:
            next_sequence += 1
        connection.execute(
            sa.text(
                "UPDATE harness_events SET sequence = :sequence "
                "WHERE workspace_id = :workspace_id AND id = :id"
            ),
            {
                "sequence": next_sequence,
                "workspace_id": row.workspace_id,
                "id": row.id,
            },
        )
    with op.batch_alter_table("harness_events") as batch_op:
        batch_op.alter_column("sequence", existing_type=sa.BigInteger(), nullable=False)
    op.create_index(
        "ix_harness_events_workspace_sequence",
        "harness_events",
        ["workspace_id", "sequence", "id"],
    )
    with op.batch_alter_table("harness_events") as batch_op:
        batch_op.create_unique_constraint(
            "uq_harness_events_sequence", ["workspace_id", "sequence"]
        )


def downgrade() -> None:
    """Remove durable harness event ordering."""

    op.drop_index("ix_harness_events_workspace_sequence", table_name="harness_events")
    with op.batch_alter_table("harness_events") as batch_op:
        batch_op.drop_constraint("uq_harness_events_sequence", type_="unique")
        batch_op.drop_column("sequence")
