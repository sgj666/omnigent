"""Add persistence tables for the Feishu team harness.

Revision ID: za1b2c3d4e5f
Revises: c4d5e6f7a8b9
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "za1b2c3d4e5f"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _workspace_id() -> sa.Column[sa.BigInteger]:
    return sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0")


def _id() -> sa.Column[Uuid16]:
    return sa.Column("id", Uuid16(), nullable=False)


def upgrade() -> None:
    """Create the workspace-scoped team-harness state tables."""
    op.create_table(
        "teams",
        _workspace_id(),
        _id(),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("coordinator_id", Uuid16(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index("ix_teams_status", "teams", ["workspace_id", "status", "id"])
    op.create_table(
        "agent_profiles",
        _workspace_id(),
        _id(),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("capabilities", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index("ix_agent_profiles_role", "agent_profiles", ["workspace_id", "role", "id"])
    op.create_table(
        "team_members",
        _workspace_id(),
        _id(),
        sa.Column("team_id", Uuid16(), nullable=False),
        sa.Column("agent_profile_id", Uuid16(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id", "team_id", "agent_profile_id", name="uq_team_members_team_profile"
        ),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["workspace_id", "team_id", "id"])
    op.create_table(
        "workspace_bundles",
        _workspace_id(),
        _id(),
        sa.Column("root_path", sa.String(2048), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_table(
        "workspace_repositories",
        _workspace_id(),
        _id(),
        sa.Column("workspace_bundle_id", Uuid16(), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "workspace_bundle_id",
            "name",
            name="uq_workspace_repositories_bundle_name",
        ),
    )
    op.create_index(
        "ix_workspace_repositories_bundle_id",
        "workspace_repositories",
        ["workspace_id", "workspace_bundle_id", "id"],
    )
    op.create_table(
        "runs",
        _workspace_id(),
        _id(),
        sa.Column("team_id", Uuid16(), nullable=False),
        sa.Column("workspace_bundle_id", Uuid16(), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index("ix_runs_team_status", "runs", ["workspace_id", "team_id", "status", "id"])
    op.create_table(
        "run_tasks",
        _workspace_id(),
        _id(),
        sa.Column("run_id", Uuid16(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_run_tasks_run_status", "run_tasks", ["workspace_id", "run_id", "status", "id"]
    )
    op.create_table(
        "task_dependencies",
        _workspace_id(),
        _id(),
        sa.Column("task_id", Uuid16(), nullable=False),
        sa.Column("depends_on_task_id", Uuid16(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id", "task_id", "depends_on_task_id", name="uq_task_dependencies_edge"
        ),
    )
    op.create_index(
        "ix_task_dependencies_task_id", "task_dependencies", ["workspace_id", "task_id", "id"]
    )
    op.create_table(
        "attempts",
        _workspace_id(),
        _id(),
        sa.Column("task_id", Uuid16(), nullable=False),
        sa.Column("agent_profile_id", Uuid16(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_attempts_task_status", "attempts", ["workspace_id", "task_id", "status", "id"]
    )
    op.create_table(
        "harness_events",
        _workspace_id(),
        _id(),
        sa.Column("event_id", sa.String(256), nullable=False),
        sa.Column("run_id", Uuid16(), nullable=True),
        sa.Column("task_id", Uuid16(), nullable=True),
        sa.Column("attempt_id", Uuid16(), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "event_id", name="uq_harness_events_event_id"),
    )
    op.create_index(
        "ix_harness_events_attempt_id", "harness_events", ["workspace_id", "attempt_id", "id"]
    )
    op.create_table(
        "artifacts",
        _workspace_id(),
        _id(),
        sa.Column("run_id", Uuid16(), nullable=False),
        sa.Column("task_id", Uuid16(), nullable=True),
        sa.Column("attempt_id", Uuid16(), nullable=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("location", sa.String(2048), nullable=False),
        sa.Column("content_type", sa.String(256), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["workspace_id", "run_id", "id"])
    op.create_table(
        "feishu_installations",
        _workspace_id(),
        _id(),
        sa.Column("team_id", Uuid16(), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=True),
        sa.Column("app_id", sa.String(256), nullable=False),
        sa.Column("app_secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "app_id", name="uq_feishu_installations_app_id"),
    )
    op.create_index(
        "ix_feishu_installations_team_id",
        "feishu_installations",
        ["workspace_id", "team_id", "id"],
    )
    op.create_table(
        "feishu_notifications",
        _workspace_id(),
        _id(),
        sa.Column("installation_id", Uuid16(), nullable=False),
        sa.Column("run_id", Uuid16(), nullable=True),
        sa.Column("account_id", sa.String(128), nullable=True),
        sa.Column("event_id", sa.String(256), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_feishu_notifications_installation_id",
        "feishu_notifications",
        ["workspace_id", "installation_id", "id"],
    )
    op.create_table(
        "idempotency_keys",
        _workspace_id(),
        _id(),
        sa.Column("scope", sa.String(128), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("resource_id", Uuid16(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "scope", "key", name="uq_idempotency_keys_scope_key"),
    )
    op.create_index(
        "ix_idempotency_keys_expires_at", "idempotency_keys", ["workspace_id", "expires_at", "id"]
    )


def downgrade() -> None:
    """Drop the team-harness state tables and their indexes."""
    for index, table in (
        ("ix_idempotency_keys_expires_at", "idempotency_keys"),
        ("ix_feishu_notifications_installation_id", "feishu_notifications"),
        ("ix_feishu_installations_team_id", "feishu_installations"),
        ("ix_artifacts_run_id", "artifacts"),
        ("ix_harness_events_attempt_id", "harness_events"),
        ("ix_attempts_task_status", "attempts"),
        ("ix_task_dependencies_task_id", "task_dependencies"),
        ("ix_run_tasks_run_status", "run_tasks"),
        ("ix_runs_team_status", "runs"),
        ("ix_workspace_repositories_bundle_id", "workspace_repositories"),
        ("ix_team_members_team_id", "team_members"),
        ("ix_agent_profiles_role", "agent_profiles"),
        ("ix_teams_status", "teams"),
    ):
        op.drop_index(index, table_name=table)
    for table in (
        "idempotency_keys",
        "feishu_notifications",
        "feishu_installations",
        "artifacts",
        "harness_events",
        "attempts",
        "task_dependencies",
        "run_tasks",
        "runs",
        "workspace_repositories",
        "workspace_bundles",
        "team_members",
        "agent_profiles",
        "teams",
    ):
        op.drop_table(table)
