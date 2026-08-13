"""Add workspace-scoped Skills repository configuration.

Revision ID: zm1a2b3c4d5e
Revises: zl0a1b2c3d4e
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "zm1a2b3c4d5e"
down_revision: str | None = "zl0a1b2c3d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_repository_configs",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("remote_url", sa.String(2048), nullable=False),
        sa.Column("ref", sa.String(256), nullable=False),
        sa.Column("skills_path", sa.String(1024), nullable=False),
        sa.Column("username", sa.String(256), nullable=True),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
    )


def downgrade() -> None:
    op.drop_table("skill_repository_configs")
