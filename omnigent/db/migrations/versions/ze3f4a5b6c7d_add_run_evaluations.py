"""Add versioned Run evaluation records.

Revision ID: ze3f4a5b6c7d
Revises: zd2e3f4a5b6c
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "ze3f4a5b6c7d"
down_revision: str | None = "zd2e3f4a5b6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_evaluations",
        sa.Column("workspace_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("run_id", Uuid16(), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=False),
        sa.Column("evaluator", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("metrics", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "run_id",
            "evaluator",
            "version",
            name="uq_run_evaluations_evaluator_version",
        ),
    )
    op.create_index(
        "ix_run_evaluations_owner_run",
        "run_evaluations",
        ["workspace_id", "owner_user_id", "run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_evaluations_owner_run", table_name="run_evaluations")
    op.drop_table("run_evaluations")
