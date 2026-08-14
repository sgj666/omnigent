"""Link delivery plan tasks to the product Task board.

Revision ID: zo3c4d5e6f7g
Revises: zn2b3c4d5e6f
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zo3c4d5e6f7g"
down_revision: str | None = "zn2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("work_items") as batch:
        batch.add_column(sa.Column("parent_work_item_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("task_kind", sa.String(32), nullable=False, server_default="general"))
        batch.add_column(sa.Column("assignee_worker_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("delivery_run_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("planned_task_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("task_key", sa.String(128), nullable=True))
        batch.add_column(sa.Column("depends_on", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("artifact_requirements", sa.Text(), nullable=False, server_default="[]"))
        batch.create_index("ix_work_items_delivery_task", ["workspace_id", "delivery_run_id", "task_key"], unique=True)
        batch.create_index("ix_work_items_parent", ["workspace_id", "parent_work_item_id", "id"])
    with op.batch_alter_table("delivery_planned_tasks") as batch:
        batch.alter_column("owner_role", existing_type=sa.String(128), nullable=True)
        batch.add_column(sa.Column("work_item_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch.add_column(sa.Column("task_kind", sa.String(32), nullable=False, server_default="delivery"))
        batch.add_column(sa.Column("parent_task_key", sa.String(128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("delivery_planned_tasks") as batch:
        batch.drop_column("parent_task_key")
        batch.drop_column("task_kind")
        batch.drop_column("description")
        batch.drop_column("work_item_id")
        batch.alter_column("owner_role", existing_type=sa.String(128), nullable=False)
    with op.batch_alter_table("work_items") as batch:
        batch.drop_index("ix_work_items_parent")
        batch.drop_index("ix_work_items_delivery_task")
        batch.drop_column("artifact_requirements")
        batch.drop_column("depends_on")
        batch.drop_column("task_key")
        batch.drop_column("planned_task_id")
        batch.drop_column("delivery_run_id")
        batch.drop_column("assignee_worker_name")
        batch.drop_column("task_kind")
        batch.drop_column("parent_work_item_id")
