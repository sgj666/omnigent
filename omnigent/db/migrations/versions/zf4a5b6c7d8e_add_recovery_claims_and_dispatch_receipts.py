"""Add Host recovery claims and durable runner dispatch receipts.

Revision ID: zf4a5b6c7d8e
Revises: ze3f4a5b6c7d
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "zf4a5b6c7d8e"
down_revision: str | None = "ze3f4a5b6c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "omnigent_conversation_metadata",
        sa.Column("recovery_attempt_id", Uuid16(), nullable=True),
    )
    op.add_column(
        "omnigent_conversation_metadata",
        sa.Column("recovery_runner_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "omnigent_conversation_metadata",
        sa.Column("recovery_workspace", sa.String(2048), nullable=True),
    )
    op.create_index(
        "ix_conversation_metadata_recovery_attempt_id",
        "omnigent_conversation_metadata",
        ["workspace_id", "recovery_attempt_id", "id"],
    )
    op.create_table(
        "runner_dispatch_receipts",
        sa.Column("workspace_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("conversation_id", Uuid16(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("runner_id", sa.String(64), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("persisted_item_id", Uuid16(), nullable=False),
        sa.Column("enqueue_position", sa.Integer(), nullable=False),
        sa.Column("execution_owner_id", sa.String(64), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.Integer(), nullable=True),
        sa.Column(
            "effects_status",
            sa.String(16),
            server_default="completed",
            nullable=False,
        ),
        sa.Column("effects_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("effects_last_error", sa.Text(), nullable=True),
        sa.Column("effects_completed_at", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "phase IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_runner_dispatch_receipts_phase",
        ),
        sa.CheckConstraint(
            "effects_status IN ('pending', 'completed')",
            name="ck_runner_dispatch_receipts_effects_status",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "conversation_id", "idempotency_key"),
    )
    op.create_index(
        "ix_runner_dispatch_receipts_recoverable",
        "runner_dispatch_receipts",
        [
            "workspace_id",
            "runner_id",
            "phase",
            "conversation_id",
            "enqueue_position",
        ],
    )
    op.create_index(
        "ix_runner_dispatch_receipts_gc",
        "runner_dispatch_receipts",
        ["workspace_id", "phase", "completed_at"],
    )
    op.create_index(
        "ix_runner_dispatch_receipts_pending_effects",
        "runner_dispatch_receipts",
        ["workspace_id", "effects_status", "updated_at", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runner_dispatch_receipts_pending_effects",
        table_name="runner_dispatch_receipts",
    )
    op.drop_index(
        "ix_runner_dispatch_receipts_gc",
        table_name="runner_dispatch_receipts",
    )
    op.drop_index(
        "ix_runner_dispatch_receipts_recoverable",
        table_name="runner_dispatch_receipts",
    )
    op.drop_table("runner_dispatch_receipts")
    op.drop_index(
        "ix_conversation_metadata_recovery_attempt_id",
        table_name="omnigent_conversation_metadata",
    )
    with op.batch_alter_table("omnigent_conversation_metadata") as batch_op:
        batch_op.drop_column("recovery_workspace")
        batch_op.drop_column("recovery_runner_id")
        batch_op.drop_column("recovery_attempt_id")
