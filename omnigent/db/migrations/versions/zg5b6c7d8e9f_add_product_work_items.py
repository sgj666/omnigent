"""Add owner-private product Tasks.

Revision ID: zg5b6c7d8e9f
Revises: zf4a5b6c7d8e
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zg5b6c7d8e9f"
down_revision: str | None = "zf4a5b6c7d8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_items",
        sa.Column("workspace_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=True),
        sa.Column("project_id", Uuid16(), nullable=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="2", nullable=False),
        sa.Column("assignee_agent_id", Uuid16(), nullable=True),
        sa.Column("due_at", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("state IN (1, 2, 3, 4, 5, 6)", name="ck_work_items_state"),
        sa.CheckConstraint("priority IN (1, 2, 3, 4)", name="ck_work_items_priority"),
        sa.CheckConstraint("version >= 1", name="ck_work_items_version"),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_work_items_owner_state",
        "work_items",
        ["workspace_id", "owner_user_id", "state", "updated_at", "id"],
    )
    op.create_index(
        "ix_work_items_project",
        "work_items",
        ["workspace_id", "project_id", "state", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_work_items_project", table_name="work_items")
    op.drop_index("ix_work_items_owner_state", table_name="work_items")
    op.drop_table("work_items")
