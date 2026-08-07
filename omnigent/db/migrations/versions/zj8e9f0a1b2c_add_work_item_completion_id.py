"""Add stable Task completion occurrence identifiers.

Revision ID: zj8e9f0a1b2c
Revises: zi7d8e9f0a1b
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zj8e9f0a1b2c"
down_revision: str | None = "zi7d8e9f0a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_items",
        sa.Column("completion_id", Uuid16(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("work_items") as batch_op:
        batch_op.drop_column("completion_id")
