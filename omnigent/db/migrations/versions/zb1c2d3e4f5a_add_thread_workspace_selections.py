"""Add durable team-harness thread workspace selections.

Revision ID: zb1c2d3e4f5a
Revises: za1b2c3d4e5f
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zb1c2d3e4f5a"
down_revision: str | None = "za1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one workspace-default row per workspace/thread/scope."""
    op.create_table(
        "thread_workspace_selections",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("thread_id", sa.String(256), nullable=False),
        sa.Column("scope", sa.String(128), nullable=False, server_default=""),
        sa.Column("selected_workspace_id", Uuid16(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "thread_id", "scope"),
    )


def downgrade() -> None:
    """Drop the thread default workspace mapping."""
    op.drop_table("thread_workspace_selections")
