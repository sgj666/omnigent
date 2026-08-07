"""Assign existing Agent-created Tasks to their creator.

Revision ID: zl0a1b2c3d4e
Revises: zk9f0a1b2c3d
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "zl0a1b2c3d4e"
down_revision: str | None = "zk9f0a1b2c3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE work_items "
            "SET assignee_agent_id = created_by_agent_id "
            "WHERE creator_kind = 2 "
            "AND assignee_agent_id IS NULL "
            "AND created_by_agent_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    # The previous assignment is valid data and cannot be distinguished from
    # an explicit self-assignment, so downgrade intentionally preserves it.
    pass
