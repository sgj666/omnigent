"""Pin Session bundles and project real Session trees.

Revision ID: zc1d2e3f4a5b
Revises: zb2c3d4e5f6a
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import BINARY as MySQLBinary

from omnigent.db.db_models import Uuid16

revision: str = "zc1d2e3f4a5b"
down_revision: str | None = "zb2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
# BYTEA/BLOB elsewhere, BINARY(32) on MySQL/MariaDB so the digest is fully indexable.
_CKSUM32 = (
    sa.LargeBinary(length=32)
    .with_variant(MySQLBinary(32), "mysql")
    .with_variant(MySQLBinary(32), "mariadb")
)


def upgrade() -> None:
    """Add Session-backed run projections while preserving Team-era rows."""
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("agent_bundle_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("agent_bundle_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("agent_bundle_location", sa.String(512), nullable=True))

    with op.batch_alter_table("runs") as batch:
        batch.alter_column("team_id", existing_type=Uuid16(), nullable=True)
        batch.add_column(sa.Column("agent_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("bundle_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("bundle_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("root_session_id", Uuid16(), nullable=True))
        batch.add_column(
            sa.Column(
                "legacy_state",
                sa.String(32),
                nullable=False,
                server_default="legacy_unbound",
            )
        )

    with op.batch_alter_table("run_tasks") as batch:
        batch.add_column(sa.Column("root_session_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("child_session_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("dispatch_title", sa.String(512), nullable=True))
        batch.add_column(sa.Column("purpose", sa.String(32), nullable=True))
        batch.add_column(sa.Column("source_event_id", sa.String(256), nullable=True))

    with op.batch_alter_table("attempts") as batch:
        batch.alter_column("agent_profile_id", existing_type=Uuid16(), nullable=True)
        batch.add_column(sa.Column("child_session_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("worker_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("worker_config_path", sa.String(512), nullable=True))
        batch.add_column(sa.Column("purpose", sa.String(32), nullable=True))
        batch.add_column(sa.Column("harness", sa.String(128), nullable=True))
        batch.add_column(sa.Column("model", sa.String(256), nullable=True))
        batch.add_column(sa.Column("dispatch_call_id", sa.String(256), nullable=True))
        batch.add_column(sa.Column("response_id", sa.String(256), nullable=True))
        batch.add_column(sa.Column("turn_id", sa.String(256), nullable=True))
        batch.add_column(sa.Column("started_at", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("failure_code", sa.String(128), nullable=True))
        batch.add_column(sa.Column("retry_of_attempt_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("source_event_id", sa.String(256), nullable=True))

    with op.batch_alter_table("harness_events") as batch:
        batch.add_column(sa.Column("session_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("conversation_item_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("source_kind", sa.String(64), nullable=True))
        batch.add_column(sa.Column("source_event_id", sa.String(256), nullable=True))

    with op.batch_alter_table("feishu_installations") as batch:
        batch.alter_column("team_id", existing_type=Uuid16(), nullable=True)
        batch.add_column(sa.Column("agent_id", Uuid16(), nullable=True))
        batch.add_column(sa.Column("tenant_key", sa.String(256), nullable=True))
        batch.add_column(sa.Column("bot_open_id", sa.String(256), nullable=True))
        batch.add_column(sa.Column("installer_open_id", sa.String(256), nullable=True))

    op.create_table(
        "feishu_thread_bindings",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("installation_id", Uuid16(), nullable=False),
        sa.Column("agent_id", Uuid16(), nullable=False),
        sa.Column("chat_id", sa.String(256), nullable=False),
        sa.Column("thread_id", sa.String(256), nullable=False, server_default=""),
        sa.Column("default_workspace_id", Uuid16(), nullable=True),
        sa.Column("host_id", sa.String(128), nullable=True),
        sa.Column("execution_mode", sa.String(32), nullable=False, server_default="auto"),
        sa.Column("allowed_members", sa.Text(), nullable=True),
        sa.Column("surface_status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "installation_id",
            "chat_id",
            "thread_id",
            name="uq_feishu_thread_bindings_chat_thread",
        ),
    )
    op.create_table(
        "worktree_leases",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("attempt_id", Uuid16(), nullable=True),
        sa.Column("child_session_id", Uuid16(), nullable=False),
        sa.Column("host_id", sa.String(128), nullable=False),
        sa.Column("repository_id", sa.String(256), nullable=False),
        sa.Column("worktree_path", sa.String(2048), nullable=False),
        # sha256(worktree_path.encode("utf-8")); exact bytes, no case folding.
        sa.Column("worktree_path_cksum", _CKSUM32, nullable=False),
        sa.Column("branch", sa.String(512), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("heartbeat_at", sa.Integer(), nullable=False),
        sa.Column("base_commit", sa.String(64), nullable=True),
        sa.Column("output_commit", sa.String(64), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("released_at", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "host_id",
            "worktree_path_cksum",
            name="uq_worktree_leases_host_path",
        ),
    )

    op.create_index("ix_runs_agent_status", "runs", ["workspace_id", "agent_id", "status", "id"])
    op.create_index(
        "uq_runs_root_session",
        "runs",
        ["workspace_id", "root_session_id"],
        unique=True,
    )
    op.create_index(
        "uq_run_tasks_source_event",
        "run_tasks",
        ["workspace_id", "source_event_id"],
        unique=True,
    )
    op.create_index(
        "uq_attempts_source_event",
        "attempts",
        ["workspace_id", "source_event_id"],
        unique=True,
    )
    op.create_index(
        "uq_harness_events_source",
        "harness_events",
        ["workspace_id", "source_kind", "source_event_id"],
        unique=True,
    )
    op.create_index(
        "ix_feishu_installations_agent_id",
        "feishu_installations",
        ["workspace_id", "agent_id", "id"],
    )
    op.create_index(
        "ix_feishu_thread_bindings_agent",
        "feishu_thread_bindings",
        ["workspace_id", "agent_id", "id"],
    )
    op.create_index(
        "ix_worktree_leases_child",
        "worktree_leases",
        ["workspace_id", "child_session_id", "state", "id"],
    )

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE runs SET legacy_state = 'legacy_unbound'"))
    _backfill_unique_agent_matches(connection)


def _backfill_unique_agent_matches(connection: sa.Connection) -> None:
    """Bind only unambiguous legacy coordinator/template matches."""
    legacy_runs = connection.execute(
        sa.text(
            "SELECT r.workspace_id, r.id AS run_id, p.name AS coordinator_name "
            "FROM runs r "
            "JOIN teams t ON t.workspace_id = r.workspace_id AND t.id = r.team_id "
            "JOIN agent_profiles p "
            "ON p.workspace_id = t.workspace_id AND p.id = t.coordinator_id"
        )
    ).mappings()
    for legacy_run in legacy_runs:
        matches = (
            connection.execute(
                sa.text(
                    "SELECT id, version, bundle_location FROM agents "
                    "WHERE workspace_id = :workspace_id AND kind = 1 "
                    "AND LOWER(name) = LOWER(:coordinator_name)"
                ),
                {
                    "workspace_id": legacy_run["workspace_id"],
                    "coordinator_name": legacy_run["coordinator_name"],
                },
            )
            .mappings()
            .all()
        )
        if len(matches) != 1:
            continue
        match = matches[0]
        location = match["bundle_location"]
        digest = location.rsplit("/", 1)[-1] if isinstance(location, str) else ""
        if _SHA256_RE.fullmatch(digest) is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE runs SET agent_id = :agent_id, bundle_version = :bundle_version, "
                "bundle_digest = :bundle_digest, legacy_state = 'legacy_bound' "
                "WHERE workspace_id = :workspace_id AND id = :run_id"
            ),
            {
                "agent_id": match["id"],
                "bundle_version": match["version"],
                "bundle_digest": digest,
                "workspace_id": legacy_run["workspace_id"],
                "run_id": legacy_run["run_id"],
            },
        )


def downgrade() -> None:
    """Remove projections only when all rows remain representable by legacy IDs."""
    connection = op.get_bind()
    dialect = connection.dialect
    if dialect.name in {"mysql", "mariadb"} or bool(getattr(dialect, "is_mariadb", False)):
        raise RuntimeError(
            "MySQL/MariaDB downgrade cannot safely proceed while concurrent writers may create "
            "native NULL rows between representability checks and destructive DDL. Enter "
            "maintenance mode, stop all application writes, and run the downgrade only "
            "under a writer-enforced deployment migration lock."
        )
    for table, column in (
        ("runs", "team_id"),
        ("attempts", "agent_profile_id"),
        ("feishu_installations", "team_id"),
    ):
        null_count = connection.scalar(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
        )
        if null_count:
            raise RuntimeError(
                f"{table}.{column} contains {null_count} native NULL row(s); cannot downgrade "
                "to the Team-era schema. Remove or migrate those native rows first."
            )

    for index, table in (
        ("ix_worktree_leases_child", "worktree_leases"),
        ("ix_feishu_thread_bindings_agent", "feishu_thread_bindings"),
        ("ix_feishu_installations_agent_id", "feishu_installations"),
        ("uq_harness_events_source", "harness_events"),
        ("uq_attempts_source_event", "attempts"),
        ("uq_run_tasks_source_event", "run_tasks"),
        ("uq_runs_root_session", "runs"),
        ("ix_runs_agent_status", "runs"),
    ):
        op.drop_index(index, table_name=table)

    op.drop_table("worktree_leases")
    op.drop_table("feishu_thread_bindings")

    with op.batch_alter_table("feishu_installations") as batch:
        batch.alter_column("team_id", existing_type=Uuid16(), nullable=False)
        batch.drop_column("installer_open_id")
        batch.drop_column("bot_open_id")
        batch.drop_column("tenant_key")
        batch.drop_column("agent_id")

    with op.batch_alter_table("harness_events") as batch:
        batch.drop_column("source_event_id")
        batch.drop_column("source_kind")
        batch.drop_column("conversation_item_id")
        batch.drop_column("session_id")

    with op.batch_alter_table("attempts") as batch:
        batch.alter_column("agent_profile_id", existing_type=Uuid16(), nullable=False)
        for column in (
            "source_event_id",
            "retry_of_attempt_id",
            "failure_code",
            "completed_at",
            "started_at",
            "turn_id",
            "response_id",
            "dispatch_call_id",
            "model",
            "harness",
            "purpose",
            "worker_config_path",
            "worker_name",
            "child_session_id",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("run_tasks") as batch:
        for column in (
            "source_event_id",
            "purpose",
            "dispatch_title",
            "child_session_id",
            "root_session_id",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("runs") as batch:
        batch.alter_column("team_id", existing_type=Uuid16(), nullable=False)
        batch.drop_column("legacy_state")
        batch.drop_column("root_session_id")
        batch.drop_column("bundle_digest")
        batch.drop_column("bundle_version")
        batch.drop_column("agent_id")

    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("agent_bundle_location")
        batch.drop_column("agent_bundle_digest")
        batch.drop_column("agent_bundle_version")
