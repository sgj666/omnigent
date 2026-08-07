"""Add persistent product Inbox items.

Revision ID: zi7d8e9f0a1b
Revises: zh6c7d8e9f0a
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zi7d8e9f0a1b"
down_revision: str | None = "zh6c7d8e9f0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbox_items",
        sa.Column("workspace_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=True),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("dedupe_key", sa.String(512), nullable=False),
        sa.Column("work_item_id", Uuid16(), nullable=True),
        sa.Column("work_item_run_id", Uuid16(), nullable=True),
        sa.Column("session_id", Uuid16(), nullable=True),
        sa.Column("source_id", sa.String(256), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("action_required", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.Column("read_at", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN (1, 2, 3, 4, 5, 6, 7, 8)", name="ck_inbox_items_kind"),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_inbox_items_owner_created",
        "inbox_items",
        ["workspace_id", "owner_user_id", "created_at", "id"],
    )
    op.create_index(
        "ix_inbox_items_dedupe",
        "inbox_items",
        ["workspace_id", "dedupe_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_inbox_items_dedupe", table_name="inbox_items")
    op.drop_index("ix_inbox_items_owner_created", table_name="inbox_items")
    op.drop_table("inbox_items")
