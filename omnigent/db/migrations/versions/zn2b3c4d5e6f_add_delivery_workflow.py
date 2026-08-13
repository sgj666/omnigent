"""Add profile-scoped delivery workflow state.

Revision ID: zn2b3c4d5e6f
Revises: zm1a2b3c4d5e
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zn2b3c4d5e6f"
down_revision: str | None = "zm1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delivery_runs",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("runtime_run_id", Uuid16(), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_delivery_runs_version_positive"),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "profile_id",
            "owner_user_id",
            "runtime_run_id",
            name="uq_delivery_runs_profile_owner_runtime",
        ),
    )
    op.create_index(
        "ix_delivery_runs_profile_owner_status",
        "delivery_runs",
        ["workspace_id", "profile_id", "owner_user_id", "status", "updated_at", "id"],
    )
    op.create_table(
        "delivery_planned_tasks",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("delivery_run_id", Uuid16(), nullable=False),
        sa.Column("task_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("owner_role", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("depends_on", sa.Text(), nullable=False),
        sa.Column("artifact_requirements", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "delivery_run_id",
            "task_key",
            name="uq_delivery_planned_tasks_run_key",
        ),
    )
    op.create_index(
        "ix_delivery_planned_tasks_run",
        "delivery_planned_tasks",
        ["workspace_id", "delivery_run_id", "status", "task_key"],
    )
    op.create_table(
        "delivery_artifacts",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("delivery_run_id", Uuid16(), nullable=False),
        sa.Column("planned_task_id", Uuid16(), nullable=True),
        sa.Column("kind", sa.String(128), nullable=False),
        sa.Column("location", sa.String(2048), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_delivery_artifacts_run",
        "delivery_artifacts",
        ["workspace_id", "delivery_run_id", "created_at", "id"],
    )
    op.create_table(
        "delivery_transitions",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("delivery_run_id", Uuid16(), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("from_phase", sa.String(32), nullable=False),
        sa.Column("to_phase", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=False),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("evidence_refs", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "profile_id",
            "delivery_run_id",
            "idempotency_key",
            name="uq_delivery_transitions_idempotency",
        ),
    )
    op.create_index(
        "ix_delivery_transitions_run",
        "delivery_transitions",
        ["workspace_id", "delivery_run_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_transitions_run", table_name="delivery_transitions")
    op.drop_table("delivery_transitions")
    op.drop_index("ix_delivery_artifacts_run", table_name="delivery_artifacts")
    op.drop_table("delivery_artifacts")
    op.drop_index("ix_delivery_planned_tasks_run", table_name="delivery_planned_tasks")
    op.drop_table("delivery_planned_tasks")
    op.drop_index("ix_delivery_runs_profile_owner_status", table_name="delivery_runs")
    op.drop_table("delivery_runs")
