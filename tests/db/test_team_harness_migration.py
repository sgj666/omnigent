"""Structure checks for the team-harness persistence migration."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.dialects.mysql import mariadb
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

import omnigent.db
from omnigent.db import db_models
from omnigent.db.db_models import SqlWorktreeLease, Uuid16
from omnigent.db.migrations.versions import (
    zc1d2e3f4a5b_pin_bundle_and_project_sessions as projection_migration,
)
from omnigent.db.utils import clear_engine_cache, get_or_create_engine

_TABLES = {
    "teams",
    "agent_profiles",
    "team_members",
    "workspace_bundles",
    "workspace_repositories",
    "runs",
    "run_tasks",
    "task_dependencies",
    "attempts",
    "harness_events",
    "artifacts",
    "feishu_installations",
    "feishu_notifications",
    "idempotency_keys",
    "thread_workspace_selections",
    "feishu_thread_bindings",
    "worktree_leases",
}

_PRE_PROJECTION_REVISION = "zb2c3d4e5f6a"
_PROJECTION_REVISION = "zc1d2e3f4a5b"


def _alembic_config(uri: str) -> Config:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(omnigent.db.__file__).parent / "migrations")
    )
    config.set_main_option("sqlalchemy.url", uri)
    return config


@pytest.fixture
def projection_db(tmp_path: Path) -> Iterator[tuple[Config, Engine]]:
    """Database parked immediately before the Session-projection revision."""
    uri = f"sqlite:///{tmp_path / 'projection.db'}"
    config = _alembic_config(uri)
    command.upgrade(config, _PRE_PROJECTION_REVISION)
    engine = sa.create_engine(uri)
    try:
        yield config, engine
    finally:
        engine.dispose()


def _uuid(value: str) -> bytes:
    return bytes.fromhex(value)


def _seed_legacy_run(
    connection: Connection,
    *,
    workspace_id: int = 7,
    team_id: str = "1" * 32,
    profile_id: str = "2" * 32,
    coordinator_name: str = "Polly Copy",
    run_id: str = "3" * 32,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO agent_profiles "
            "(workspace_id, id, name, role, created_at) "
            "VALUES (:workspace_id, :id, :name, 'coordinator', 1)"
        ),
        {"workspace_id": workspace_id, "id": _uuid(profile_id), "name": coordinator_name},
    )
    connection.execute(
        sa.text(
            "INSERT INTO teams "
            "(workspace_id, id, name, coordinator_id, status, created_at) "
            "VALUES (:workspace_id, :id, 'Legacy Team', :coordinator_id, 'active', 1)"
        ),
        {
            "workspace_id": workspace_id,
            "id": _uuid(team_id),
            "coordinator_id": _uuid(profile_id),
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO runs "
            "(workspace_id, id, team_id, source, status, created_at) "
            "VALUES (:workspace_id, :id, :team_id, 'legacy', 'queued', 1)"
        ),
        {"workspace_id": workspace_id, "id": _uuid(run_id), "team_id": _uuid(team_id)},
    )


def _seed_template_agent(
    connection: Connection,
    *,
    agent_id: str,
    name: str,
    bundle_location: str,
    version: int = 1,
    workspace_id: int = 7,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO agents "
            "(workspace_id, id, created_at, name, bundle_location, version, kind) "
            "VALUES (:workspace_id, :id, 1, :name, :bundle_location, :version, 1)"
        ),
        {
            "workspace_id": workspace_id,
            "id": _uuid(agent_id),
            "name": name,
            "bundle_location": bundle_location,
            "version": version,
        },
    )


def _upgrade_projection(config: Config) -> None:
    command.upgrade(config, _PROJECTION_REVISION)


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    """Fresh SQLite database migrated to the current schema head."""
    engine = get_or_create_engine(f"sqlite:///{tmp_path / 'team-harness.db'}")
    try:
        yield engine
    finally:
        clear_engine_cache()


def test_migration_creates_team_harness_tables(db_engine: Engine) -> None:
    """All team-harness state tables exist after a fresh migration."""
    assert set(sa.inspect(db_engine).get_table_names()) >= _TABLES


@pytest.mark.parametrize("table", sorted(_TABLES))
def test_workspace_id_leads_team_harness_primary_keys(db_engine: Engine, table: str) -> None:
    """Each table uses the existing workspace partition as its leading key."""
    primary_key = sa.inspect(db_engine).get_pk_constraint(table)["constrained_columns"]
    assert primary_key and primary_key[0] == "workspace_id"


def test_harness_event_id_is_workspace_unique(db_engine: Engine) -> None:
    """A delivered harness event can be deduplicated by its external event id."""
    inspector = sa.inspect(db_engine)
    event_columns = {column["name"] for column in inspector.get_columns("harness_events")}
    assert {"event_id", "event_type", "payload", "created_at"} <= event_columns
    unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("harness_events")
    }
    index_sets = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("harness_events")
        if index["unique"]
    }
    assert ("workspace_id", "event_id") in unique_sets | index_sets


def test_idempotency_scope_and_key_are_workspace_unique(db_engine: Engine) -> None:
    """Idempotent requests share one durable workspace/scope/key identity."""
    inspector = sa.inspect(db_engine)
    unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("idempotency_keys")
    }
    index_sets = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("idempotency_keys")
        if index["unique"]
    }
    assert ("workspace_id", "scope", "key") in unique_sets | index_sets


def test_feishu_installation_keeps_only_encrypted_secret_material(db_engine: Engine) -> None:
    """The Feishu app secret is persisted as ciphertext, never plaintext."""
    columns = {
        column["name"] for column in sa.inspect(db_engine).get_columns("feishu_installations")
    }
    assert "app_secret_ciphertext" in columns
    assert "app_secret" not in columns
    assert "app_secret_plaintext" not in columns


def test_team_harness_relationships_do_not_add_database_foreign_keys(db_engine: Engine) -> None:
    """Relationships remain application-owned, consistent with Rule R032."""
    inspector = sa.inspect(db_engine)
    assert all(inspector.get_foreign_keys(table) == [] for table in _TABLES)


def test_thread_workspace_selection_is_scoped_by_thread_and_scope(db_engine: Engine) -> None:
    """The selection migration uses workspace/thread/scope as its durable key."""
    assert sa.inspect(db_engine).get_pk_constraint("thread_workspace_selections")[
        "constrained_columns"
    ] == ["workspace_id", "thread_id", "scope"]


def test_runtime_projection_preserves_legacy_and_backfills_unique_template(
    projection_db: tuple[Config, Engine],
) -> None:
    """One valid same-workspace Template pins a legacy Run without deleting it."""
    config, engine = projection_db
    digest = "d" * 64
    with engine.begin() as connection:
        _seed_legacy_run(connection, coordinator_name="Polly Copy")
        _seed_template_agent(
            connection,
            agent_id="4" * 32,
            name="polly copy",
            version=6,
            bundle_location=f"{'4' * 32}/{digest}",
        )
        connection.execute(
            sa.text(
                "INSERT INTO feishu_installations "
                "(workspace_id, id, team_id, app_id, app_secret_ciphertext, status, created_at) "
                "VALUES (7, :id, :team_id, 'cli_legacy', :secret, 'active', 1)"
            ),
            {"id": _uuid("5" * 32), "team_id": _uuid("1" * 32), "secret": b"cipher"},
        )

    _upgrade_projection(config)

    with engine.connect() as connection:
        run = (
            connection.execute(
                sa.text(
                    "SELECT team_id, agent_id, bundle_version, bundle_digest, "
                    "root_session_id, legacy_state FROM runs"
                )
            )
            .mappings()
            .one()
        )
        installation = (
            connection.execute(
                sa.text(
                    "SELECT team_id, agent_id, tenant_key, bot_open_id, installer_open_id "
                    "FROM feishu_installations"
                )
            )
            .mappings()
            .one()
        )
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM teams")) == 1
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM agent_profiles")) == 1
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM runs")) == 1

    assert dict(run) == {
        "team_id": _uuid("1" * 32),
        "agent_id": _uuid("4" * 32),
        "bundle_version": 6,
        "bundle_digest": digest,
        "root_session_id": None,
        "legacy_state": "legacy_bound",
    }
    assert dict(installation) == {
        "team_id": _uuid("1" * 32),
        "agent_id": None,
        "tenant_key": None,
        "bot_open_id": None,
        "installer_open_id": None,
    }


@pytest.mark.parametrize(
    "matches",
    [
        [],
        [("4" * 32, "e" * 64), ("5" * 32, "f" * 64)],
        [("4" * 32, "D" * 64)],
        [("4" * 32, "g" * 64)],
    ],
    ids=["unmatched", "ambiguous", "uppercase-digest", "non-hex-digest"],
)
def test_runtime_projection_leaves_unsafe_legacy_matches_unbound(
    projection_db: tuple[Config, Engine],
    matches: list[tuple[str, str]],
) -> None:
    """Zero/multiple matches and non-lowercase SHA-256 suffixes remain unbound."""
    config, engine = projection_db
    with engine.begin() as connection:
        _seed_legacy_run(connection, coordinator_name="Candidate")
        for agent_id, digest in matches:
            _seed_template_agent(
                connection,
                agent_id=agent_id,
                name="Candidate",
                bundle_location=f"{agent_id}/{digest}",
            )

    _upgrade_projection(config)

    with engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    "SELECT agent_id, bundle_version, bundle_digest, root_session_id, "
                    "legacy_state "
                    "FROM runs"
                )
            )
            .mappings()
            .one()
        )
    assert dict(row) == {
        "agent_id": None,
        "bundle_version": None,
        "bundle_digest": None,
        "root_session_id": None,
        "legacy_state": "legacy_unbound",
    }


def test_runtime_projection_columns_indexes_and_new_tables(db_engine: Engine) -> None:
    """Head schema exactly exposes the Session-backed projection storage."""
    inspector = sa.inspect(db_engine)
    expected_columns = {
        "conversations": {
            "agent_bundle_version",
            "agent_bundle_digest",
            "agent_bundle_location",
        },
        "runs": {
            "agent_id",
            "bundle_version",
            "bundle_digest",
            "root_session_id",
            "legacy_state",
        },
        "run_tasks": {
            "root_session_id",
            "child_session_id",
            "dispatch_title",
            "purpose",
            "source_event_id",
        },
        "attempts": {
            "child_session_id",
            "worker_name",
            "worker_config_path",
            "purpose",
            "harness",
            "model",
            "dispatch_call_id",
            "response_id",
            "turn_id",
            "started_at",
            "completed_at",
            "failure_code",
            "retry_of_attempt_id",
            "source_event_id",
        },
        "harness_events": {
            "session_id",
            "conversation_item_id",
            "source_kind",
            "source_event_id",
        },
        "feishu_installations": {
            "agent_id",
            "tenant_key",
            "bot_open_id",
            "installer_open_id",
        },
        "feishu_thread_bindings": {
            "workspace_id",
            "id",
            "installation_id",
            "agent_id",
            "chat_id",
            "thread_id",
            "default_workspace_id",
            "host_id",
            "execution_mode",
            "allowed_members",
            "surface_status",
            "created_at",
            "updated_at",
        },
        "worktree_leases": {
            "workspace_id",
            "id",
            "attempt_id",
            "child_session_id",
            "host_id",
            "repository_id",
            "worktree_path",
            "worktree_path_cksum",
            "branch",
            "owner_id",
            "state",
            "heartbeat_at",
            "base_commit",
            "output_commit",
            "created_at",
            "released_at",
        },
    }
    for table, expected in expected_columns.items():
        assert expected <= {column["name"] for column in inspector.get_columns(table)}

    nullability = {
        table: {column["name"]: column["nullable"] for column in inspector.get_columns(table)}
        for table in ("runs", "attempts", "feishu_installations")
    }
    assert nullability["runs"]["team_id"] is True
    assert nullability["attempts"]["agent_profile_id"] is True
    assert nullability["feishu_installations"]["team_id"] is True
    assert nullability["runs"]["legacy_state"] is False
    worktree_columns = {
        column["name"]: column for column in inspector.get_columns("worktree_leases")
    }
    assert worktree_columns["worktree_path_cksum"]["nullable"] is False

    expected_indexes = {
        "runs": {
            "ix_runs_agent_status": (False, ("workspace_id", "agent_id", "status", "id")),
            "uq_runs_root_session": (True, ("workspace_id", "root_session_id")),
        },
        "run_tasks": {"uq_run_tasks_source_event": (True, ("workspace_id", "source_event_id"))},
        "attempts": {"uq_attempts_source_event": (True, ("workspace_id", "source_event_id"))},
        "harness_events": {
            "uq_harness_events_source": (
                True,
                ("workspace_id", "source_kind", "source_event_id"),
            )
        },
        "feishu_installations": {
            "ix_feishu_installations_agent_id": (False, ("workspace_id", "agent_id", "id"))
        },
        "feishu_thread_bindings": {
            "ix_feishu_thread_bindings_agent": (False, ("workspace_id", "agent_id", "id"))
        },
        "worktree_leases": {
            "ix_worktree_leases_child": (
                False,
                ("workspace_id", "child_session_id", "state", "id"),
            )
        },
    }
    for table, expected in expected_indexes.items():
        actual = {
            index["name"]: (index["unique"], tuple(index["column_names"]))
            for index in inspector.get_indexes(table)
        }
        assert expected.items() <= actual.items()

    assert inspector.get_pk_constraint("feishu_thread_bindings")["constrained_columns"] == [
        "workspace_id",
        "id",
    ]
    assert inspector.get_pk_constraint("worktree_leases")["constrained_columns"] == [
        "workspace_id",
        "id",
    ]
    worktree_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("worktree_leases")
    }
    assert worktree_uniques["uq_worktree_leases_host_path"] == (
        "workspace_id",
        "host_id",
        "worktree_path_cksum",
    )
    assert all(inspector.get_foreign_keys(table) == [] for table in expected_columns)


def test_worktree_path_checksum_uses_exact_utf8_bytes() -> None:
    """Lease uniqueness hashes the exact path bytes without case folding."""
    checksum = getattr(db_models, "worktree_path_cksum", None)
    assert checksum is not None, "db_models.worktree_path_cksum must define the write contract"
    assert checksum("/Repo/Ä") == hashlib.sha256(bytes("/Repo/Ä", "utf-8")).digest()
    assert checksum("/Repo/Ä") != checksum("/repo/ä")


@pytest.mark.parametrize(
    ("dialect", "binary_type"),
    [(sqlite.dialect(), "BLOB"), (postgresql.dialect(), "BYTEA")],
    ids=["sqlite", "postgresql"],
)
def test_worktree_lease_ddl_uses_fixed_checksum_key(
    dialect: sa.engine.Dialect,
    binary_type: str,
) -> None:
    """SQLite/Postgres DDL keeps the full path but keys on a fixed digest."""
    ddl = " ".join(
        str(sa.schema.CreateTable(SqlWorktreeLease.__table__).compile(dialect=dialect)).split()
    )
    assert f"worktree_path_cksum {binary_type} NOT NULL" in ddl
    assert "UNIQUE (workspace_id, host_id, worktree_path_cksum)" in ddl
    assert "UNIQUE (workspace_id, host_id, worktree_path)" not in ddl


def test_worktree_lease_mysql_unique_key_fits_utf8mb4_limit() -> None:
    """MySQL indexes the 32-byte digest, not the 2048-char utf8mb4 path."""
    ddl = " ".join(
        str(
            sa.schema.CreateTable(SqlWorktreeLease.__table__).compile(dialect=mysql.dialect())
        ).split()
    )
    assert "worktree_path_cksum BINARY(32) NOT NULL" in ddl
    assert "UNIQUE (workspace_id, host_id, worktree_path_cksum)" in ddl
    assert "UNIQUE (workspace_id, host_id, worktree_path)" not in ddl
    # BIGINT + VARCHAR(128) at utf8mb4's four bytes/char + BINARY(32).
    assert 8 + (128 * 4) + 32 <= 3072


def test_worktree_lease_mariadb_ddl_uses_fixed_binary_keys() -> None:
    """MariaDB can index the lease UUID and checksum key columns directly."""
    ddl = " ".join(
        str(
            sa.schema.CreateTable(SqlWorktreeLease.__table__).compile(
                dialect=mariadb.MariaDBDialect()
            )
        ).split()
    )

    assert "id BINARY(16) NOT NULL" in ddl
    assert "attempt_id BINARY(16)" in ddl
    assert "child_session_id BINARY(16) NOT NULL" in ddl
    assert "worktree_path_cksum BINARY(32) NOT NULL" in ddl
    assert "PRIMARY KEY (workspace_id, id)" in ddl
    assert "UNIQUE (workspace_id, host_id, worktree_path_cksum)" in ddl
    assert "BLOB(16)" not in ddl
    assert "BLOB(32)" not in ddl


def test_uuid16_mariadb_ddl_uses_binary_16_for_primary_and_related_ids() -> None:
    """Uuid16 compiles to fixed-width storage throughout MariaDB tables."""
    table = sa.Table(
        "uuid_probe",
        sa.MetaData(),
        sa.Column("id", Uuid16(), primary_key=True),
        sa.Column("parent_id", Uuid16(), nullable=False),
    )

    ddl = " ".join(
        str(sa.schema.CreateTable(table).compile(dialect=mariadb.MariaDBDialect())).split()
    )

    assert "id BINARY(16) NOT NULL" in ddl
    assert "parent_id BINARY(16) NOT NULL" in ddl
    assert "PRIMARY KEY (id)" in ddl
    assert "BLOB(16)" not in ddl


def test_projection_migration_checksum_uses_binary_32_on_mariadb() -> None:
    """MariaDB uses the same fixed-width checksum storage as MySQL."""
    table = sa.Table(
        "lease_probe",
        sa.MetaData(),
        sa.Column("worktree_path_cksum", projection_migration._CKSUM32, nullable=False),
    )

    ddl = " ".join(
        str(sa.schema.CreateTable(table).compile(dialect=mariadb.MariaDBDialect())).split()
    )

    assert "worktree_path_cksum BINARY(32) NOT NULL" in ddl
    assert "BLOB" not in ddl


def test_worktree_lease_checksum_uniqueness_preserves_full_path_semantics(
    db_engine: Engine,
) -> None:
    """Long same-prefix paths coexist; an exact duplicate path conflicts."""
    prefix = f"/repo/{'a' * 2000}"
    first_path = f"{prefix}/One"
    second_path = f"{prefix}/one"

    def values(row_id: str, path: str) -> dict[str, object]:
        return {
            "id": _uuid(row_id),
            "child_session_id": _uuid(row_id),
            "path": path,
            "path_cksum": hashlib.sha256(path.encode("utf-8")).digest(),
        }

    insert = sa.text(
        "INSERT INTO worktree_leases "
        "(workspace_id, id, child_session_id, host_id, repository_id, worktree_path, "
        "worktree_path_cksum, branch, owner_id, state, heartbeat_at, created_at) "
        "VALUES (7, :id, :child_session_id, 'host-a', 'repo-a', :path, :path_cksum, "
        "'branch-a', 'owner-a', 'active', 1, 1)"
    )
    with db_engine.begin() as connection:
        connection.execute(insert, values("a" * 32, first_path))
        connection.execute(insert, values("b" * 32, second_path))

    with pytest.raises(IntegrityError):
        with db_engine.begin() as connection:
            connection.execute(insert, values("c" * 32, first_path))

    with db_engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT worktree_path, worktree_path_cksum FROM worktree_leases "
                "ORDER BY worktree_path"
            )
        ).all()
    assert len(rows) == 2
    assert {path for path, _ in rows} == {first_path, second_path}
    assert {bytes(checksum) for _, checksum in rows} == {
        hashlib.sha256(first_path.encode("utf-8")).digest(),
        hashlib.sha256(second_path.encode("utf-8")).digest(),
    }


def test_runtime_projection_downgrade_preserves_legacy_rows(
    projection_db: tuple[Config, Engine],
) -> None:
    """A legacy-only database downgrades without deleting Team-era rows."""
    config, engine = projection_db
    with engine.begin() as connection:
        _seed_legacy_run(connection)
        connection.execute(
            sa.text(
                "INSERT INTO run_tasks "
                "(workspace_id, id, run_id, title, status, created_at) "
                "VALUES (7, :id, :run_id, 'legacy task', 'queued', 1)"
            ),
            {"id": _uuid("6" * 32), "run_id": _uuid("3" * 32)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO attempts "
                "(workspace_id, id, task_id, agent_profile_id, status, created_at) "
                "VALUES (7, :id, :task_id, :profile_id, 'queued', 1)"
            ),
            {
                "id": _uuid("7" * 32),
                "task_id": _uuid("6" * 32),
                "profile_id": _uuid("2" * 32),
            },
        )

    _upgrade_projection(config)
    command.downgrade(config, _PRE_PROJECTION_REVISION)

    inspector = sa.inspect(engine)
    assert "feishu_thread_bindings" not in inspector.get_table_names()
    assert "worktree_leases" not in inspector.get_table_names()
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    assert "team_id" in run_columns
    assert "agent_id" not in run_columns
    assert (
        next(column for column in inspector.get_columns("runs") if column["name"] == "team_id")[
            "nullable"
        ]
        is False
    )
    assert (
        next(
            column
            for column in inspector.get_columns("attempts")
            if column["name"] == "agent_profile_id"
        )["nullable"]
        is False
    )
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM teams")) == 1
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM runs")) == 1
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM attempts")) == 1


@pytest.mark.parametrize(
    ("table", "column"),
    [("runs", "team_id"), ("attempts", "agent_profile_id")],
)
def test_runtime_projection_downgrade_rejects_native_nulls_before_mutation(
    projection_db: tuple[Config, Engine],
    table: str,
    column: str,
) -> None:
    """Downgrade fails actionably instead of fabricating removed legacy IDs."""
    config, engine = projection_db
    _upgrade_projection(config)
    with engine.begin() as connection:
        if table == "runs":
            connection.execute(
                sa.text(
                    "INSERT INTO runs "
                    "(workspace_id, id, team_id, source, status, created_at, legacy_state) "
                    "VALUES (7, :id, NULL, 'web', 'queued', 1, 'native')"
                ),
                {"id": _uuid("8" * 32)},
            )
        else:
            connection.execute(
                sa.text(
                    "INSERT INTO attempts "
                    "(workspace_id, id, task_id, agent_profile_id, status, created_at) "
                    "VALUES (7, :id, :task_id, NULL, 'queued', 1)"
                ),
                {"id": _uuid("9" * 32), "task_id": _uuid("a" * 32)},
            )

    with pytest.raises(Exception, match=rf"{table}.*{column}.*cannot downgrade"):
        command.downgrade(config, _PRE_PROJECTION_REVISION)

    inspector = sa.inspect(engine)
    assert "feishu_thread_bindings" in inspector.get_table_names()
    assert "agent_id" in {column["name"] for column in inspector.get_columns("runs")}


def test_runtime_projection_downgrade_rejects_agent_scoped_feishu_before_ddl(
    projection_db: tuple[Config, Engine],
) -> None:
    """An Agent-scoped installation blocks downgrade without a half-downgrade."""
    config, engine = projection_db
    _upgrade_projection(config)
    agent_id = "d" * 32
    installation_id = "e" * 32
    with engine.begin() as connection:
        _seed_template_agent(
            connection,
            agent_id=agent_id,
            name="feishu-agent-scoped",
            bundle_location=f"{agent_id}/{'f' * 64}",
        )
        connection.execute(
            sa.text(
                "INSERT INTO feishu_installations "
                "(workspace_id, id, team_id, agent_id, tenant_key, bot_open_id, "
                "installer_open_id, app_id, app_secret_ciphertext, status, created_at) "
                "VALUES (7, :id, NULL, :agent_id, 'tenant-native', 'bot-native', "
                "'installer-native', 'cli_native', :secret, 'active', 1)"
            ),
            {
                "id": _uuid(installation_id),
                "agent_id": _uuid(agent_id),
                "secret": b"cipher-native",
            },
        )

    tracked_tables = (
        "conversations",
        "runs",
        "run_tasks",
        "attempts",
        "harness_events",
        "feishu_installations",
        "feishu_thread_bindings",
        "worktree_leases",
    )

    def schema_state() -> tuple[
        set[str],
        dict[str, tuple[str, ...]],
        dict[str, tuple[tuple[str, tuple[str, ...], bool], ...]],
    ]:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        columns = {
            table: tuple(column["name"] for column in inspector.get_columns(table))
            for table in tracked_tables
            if table in tables
        }
        indexes = {
            table: tuple(
                sorted(
                    (
                        index["name"],
                        tuple(index["column_names"]),
                        bool(index["unique"]),
                    )
                    for index in inspector.get_indexes(table)
                )
            )
            for table in tracked_tables
            if table in tables
        }
        return tables, columns, indexes

    schema_before = schema_state()
    with engine.connect() as connection:
        version_before = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
        installation_before = (
            connection.execute(
                sa.text(
                    "SELECT team_id, agent_id, tenant_key, bot_open_id, installer_open_id, "
                    "app_id, app_secret_ciphertext, status, created_at "
                    "FROM feishu_installations WHERE workspace_id = 7 AND id = :id"
                ),
                {"id": _uuid(installation_id)},
            )
            .mappings()
            .one()
        )

    downgrade_error: Exception | None = None
    try:
        command.downgrade(config, _PRE_PROJECTION_REVISION)
    except Exception as exc:  # The regression records the actual backend failure.
        downgrade_error = exc

    schema_after = schema_state()
    with engine.connect() as connection:
        version_after = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
        installation_after = (
            connection.execute(
                sa.text(
                    "SELECT team_id, agent_id, tenant_key, bot_open_id, installer_open_id, "
                    "app_id, app_secret_ciphertext, status, created_at "
                    "FROM feishu_installations WHERE workspace_id = 7 AND id = :id"
                ),
                {"id": _uuid(installation_id)},
            )
            .mappings()
            .one()
        )

    problems: list[str] = []
    if not isinstance(downgrade_error, RuntimeError) or not (
        "feishu_installations.team_id" in str(downgrade_error)
        and "cannot downgrade" in str(downgrade_error)
    ):
        problems.append(f"unexpected downgrade error: {downgrade_error!r}")
    if schema_after != schema_before:
        problems.append(
            f"schema mutated before rejection: before={schema_before!r}, after={schema_after!r}"
        )
    if version_after != version_before:
        problems.append(f"version changed: before={version_before!r}, after={version_after!r}")
    if dict(installation_after) != dict(installation_before):
        problems.append(
            "installation changed: "
            f"before={dict(installation_before)!r}, after={dict(installation_after)!r}"
        )
    assert problems == []


def test_mysql_projection_downgrade_fails_closed_before_queries_or_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MySQL downgrade requires writer-enforced maintenance mode."""
    scalar_calls: list[object] = []
    ddl_calls: list[str] = []

    class _Connection:
        dialect = mysql.dialect()

        @staticmethod
        def scalar(statement: object) -> int:
            scalar_calls.append(statement)
            return 0

    def _record_ddl(*args: object, **kwargs: object) -> None:
        del args, kwargs
        ddl_calls.append("ddl")

    monkeypatch.setattr(projection_migration.op, "get_bind", lambda: _Connection())
    monkeypatch.setattr(projection_migration.op, "drop_index", _record_ddl)
    monkeypatch.setattr(projection_migration.op, "drop_table", _record_ddl)
    monkeypatch.setattr(projection_migration.op, "batch_alter_table", _record_ddl)

    with pytest.raises(RuntimeError) as exc_info:
        projection_migration.downgrade()

    message = str(exc_info.value)
    assert "MySQL" in message
    assert "cannot safely proceed" in message
    assert "maintenance mode" in message
    assert "stop all application writes" in message
    assert scalar_calls == []
    assert ddl_calls == []


def test_mariadb_projection_downgrade_fails_closed_before_queries_or_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MariaDB downgrade rejects before representability reads or schema changes."""
    scalar_calls: list[object] = []
    ddl_calls: list[str] = []

    class _Connection:
        dialect = mariadb.MariaDBDialect()

        @staticmethod
        def scalar(statement: object) -> int:
            scalar_calls.append(statement)
            return 0

    def _record_ddl(*args: object, **kwargs: object) -> None:
        del args, kwargs
        ddl_calls.append("ddl")

    monkeypatch.setattr(projection_migration.op, "get_bind", lambda: _Connection())
    monkeypatch.setattr(projection_migration.op, "drop_index", _record_ddl)
    monkeypatch.setattr(projection_migration.op, "drop_table", _record_ddl)
    monkeypatch.setattr(projection_migration.op, "batch_alter_table", _record_ddl)

    with pytest.raises(RuntimeError) as exc_info:
        projection_migration.downgrade()

    message = str(exc_info.value)
    assert "MariaDB" in message
    assert "cannot safely proceed" in message
    assert "maintenance mode" in message
    assert "stop all application writes" in message
    assert scalar_calls == []
    assert ddl_calls == []
