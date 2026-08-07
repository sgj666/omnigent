"""Add blocked/failed Task states and creator provenance.

Revision ID: zk9f0a1b2c3d
Revises: zj8e9f0a1b2c
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zk9f0a1b2c3d"
down_revision: str | None = "zj8e9f0a1b2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recreate_mode() -> str:
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    with op.batch_alter_table("work_items", recreate=_recreate_mode()) as batch:
        batch.drop_constraint("ck_work_items_state", type_="check")
        batch.add_column(
            sa.Column("creator_kind", sa.SmallInteger(), server_default="1", nullable=False)
        )
        batch.add_column(sa.Column("created_by_agent_id", Uuid16(), nullable=True))
        batch.create_check_constraint(
            "ck_work_items_state",
            "state IN (1, 2, 3, 4, 5, 6, 7, 8)",
        )
        batch.create_check_constraint(
            "ck_work_items_creator_kind",
            "creator_kind IN (1, 2, 3)",
        )


def downgrade() -> None:
    # Older code cannot decode the two new state codes. Preserve the tasks by
    # returning blocked/failed rows to To do before narrowing the constraint.
    op.execute(sa.text("UPDATE work_items SET state = 2 WHERE state IN (7, 8)"))
    with op.batch_alter_table("work_items", recreate=_recreate_mode()) as batch:
        batch.drop_constraint("ck_work_items_creator_kind", type_="check")
        batch.drop_constraint("ck_work_items_state", type_="check")
        batch.drop_column("created_by_agent_id")
        batch.drop_column("creator_kind")
        batch.create_check_constraint(
            "ck_work_items_state",
            "state IN (1, 2, 3, 4, 5, 6)",
        )
