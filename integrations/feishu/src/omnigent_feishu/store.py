"""Restart-safe SQLite store for Feishu provider state only."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import aiosqlite

from omnigent_feishu.models import InboundEvent, Installation, Notification, ThreadBinding

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS installations (
  id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, app_id TEXT,
  app_secret_ciphertext TEXT, installer_open_id TEXT, bot_open_id TEXT,
  status TEXT NOT NULL, device_session TEXT UNIQUE, verification_uri TEXT,
  error TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  verification_uri_base TEXT, user_code TEXT, interval INTEGER,
  expires_at INTEGER, expires_in INTEGER, tenant_key TEXT, tenant_name TEXT,
  bot_name TEXT, bot_avatar_url TEXT
);
CREATE INDEX IF NOT EXISTS installations_agent ON installations(agent_id, updated_at);
CREATE TABLE IF NOT EXISTS thread_bindings (
  id TEXT PRIMARY KEY, installation_id TEXT NOT NULL, chat_id TEXT NOT NULL,
  thread_id TEXT NOT NULL DEFAULT '', agent_id TEXT NOT NULL, workspace_id TEXT,
  run_id TEXT, host_id TEXT, execution_mode TEXT NOT NULL DEFAULT 'auto',
  allowed_members TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE(installation_id, chat_id, thread_id)
);
CREATE TABLE IF NOT EXISTS inbound_events (
  event_id TEXT PRIMARY KEY, installation_id TEXT NOT NULL, sender_id TEXT,
  status TEXT NOT NULL, run_id TEXT, error_code TEXT, created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY, installation_id TEXT NOT NULL, run_id TEXT, event_id TEXT,
  payload TEXT NOT NULL, status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at INTEGER NOT NULL, last_error TEXT, created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL, UNIQUE(installation_id, event_id)
);
CREATE INDEX IF NOT EXISTS notifications_retry ON notifications(status, next_attempt_at);
CREATE TABLE IF NOT EXISTS surfaces (
  installation_id TEXT PRIMARY KEY, surface_profile_id TEXT NOT NULL,
  surface_version INTEGER NOT NULL, status TEXT NOT NULL, surface_type TEXT NOT NULL,
  error TEXT, last_provisioned_at INTEGER NOT NULL, provider_resource_id TEXT,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_grants (
  installation_id TEXT NOT NULL, provider_user_id TEXT NOT NULL,
  access_ciphertext TEXT NOT NULL, refresh_ciphertext TEXT, expires_at INTEGER,
  updated_at INTEGER NOT NULL, PRIMARY KEY(installation_id, provider_user_id)
);
"""

_INSTALLATION_COLUMNS = {
    "verification_uri_base": "TEXT",
    "user_code": "TEXT",
    "interval": "INTEGER",
    "expires_at": "INTEGER",
    "expires_in": "INTEGER",
    "tenant_key": "TEXT",
    "tenant_name": "TEXT",
    "bot_name": "TEXT",
    "bot_avatar_url": "TEXT",
}


class FeishuStore:
    """Small async store with one transaction per durable state transition."""

    def __init__(self, path: str | Path, *, clock: Any = None) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: int(time.time()))

    def now(self) -> int:
        return int(self._clock())

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(_SCHEMA)
            existing = {
                str(row[1])
                for row in await (await db.execute("PRAGMA table_info(installations) ")).fetchall()
            }
            for name, sql_type in _INSTALLATION_COLUMNS.items():
                if name not in existing:
                    await db.execute(f"ALTER TABLE installations ADD COLUMN {name} {sql_type}")
            await db.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','1')"
            )
            await db.commit()

    async def table_columns(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            for (name,) in await cursor.fetchall():
                columns = await (await db.execute(f'PRAGMA table_info("{name}")')).fetchall()
                result[name] = {str(row[1]) for row in columns}
        return result

    async def get_meta(self, key: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute("SELECT value FROM schema_meta WHERE key=?", (key,))
            ).fetchone()
        return str(row[0]) if row else None

    async def set_meta(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES(?,?)", (key, value)
            )
            await db.commit()

    async def import_installation(
        self,
        *,
        installation_id: str,
        agent_id: str,
        app_id: str,
        app_secret_ciphertext: str,
        installer_open_id: str | None,
        bot_open_id: str | None,
        created_at: int,
    ) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """INSERT OR IGNORE INTO installations
                (id,agent_id,app_id,app_secret_ciphertext,installer_open_id,bot_open_id,
                 status,created_at,updated_at) VALUES(?,?,?,?,?,?,'connected',?,?)""",
                (
                    installation_id,
                    agent_id,
                    app_id,
                    app_secret_ciphertext,
                    installer_open_id,
                    bot_open_id,
                    created_at,
                    created_at,
                ),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def create_pending_installation(
        self,
        *,
        agent_id: str,
        session: str,
        verification_uri: str,
        verification_uri_base: str | None = None,
        user_code: str | None = None,
        interval: int | None = None,
        expires_in: int | None = None,
        installation_id: str | None = None,
    ) -> Installation:
        now = self._clock()
        installation_id = installation_id or uuid.uuid4().hex
        expires_at = now + expires_in if expires_in is not None else None
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO installations
                (id,agent_id,status,device_session,verification_uri,verification_uri_base,
                 user_code,interval,expires_at,expires_in,created_at,updated_at)
                VALUES(?,?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_session) DO UPDATE SET
                  verification_uri=excluded.verification_uri,
                  verification_uri_base=excluded.verification_uri_base,
                  user_code=excluded.user_code,interval=excluded.interval,
                  expires_at=excluded.expires_at,expires_in=excluded.expires_in,
                  status='pending',error=NULL,updated_at=excluded.updated_at""",
                (
                    installation_id,
                    agent_id,
                    session,
                    verification_uri,
                    verification_uri_base,
                    user_code,
                    interval,
                    expires_at,
                    expires_in,
                    now,
                    now,
                ),
            )
            await db.commit()
        found = await self.get_installation_by_session(session)
        assert found is not None
        return found

    async def connect_installation(
        self,
        installation_id: str,
        *,
        app_id: str,
        app_secret_ciphertext: str,
        installer_open_id: str,
        bot_open_id: str,
        tenant_key: str | None = None,
        tenant_name: str | None = None,
        bot_name: str | None = None,
        bot_avatar_url: str | None = None,
    ) -> Installation:
        now = self._clock()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE installations SET app_id=?,app_secret_ciphertext=?,
                installer_open_id=?,bot_open_id=?,tenant_key=?,tenant_name=?,bot_name=?,
                bot_avatar_url=?,status='connected',error=NULL,updated_at=?
                WHERE id=?""",
                (
                    app_id,
                    app_secret_ciphertext,
                    installer_open_id,
                    bot_open_id,
                    tenant_key,
                    tenant_name,
                    bot_name,
                    bot_avatar_url,
                    now,
                    installation_id,
                ),
            )
            await db.commit()
        found = await self.get_installation(installation_id)
        if found is None:
            raise KeyError("installation not found")
        return found

    async def mark_installation_error(self, installation_id: str, error: str) -> None:
        status = "expired" if error == "expired" else "error"
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE installations SET status=?,error=?,updated_at=? WHERE id=?",
                (status, error, self._clock(), installation_id),
            )
            await db.commit()

    async def update_pending_interval(self, installation_id: str, interval: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE installations SET interval=?,updated_at=? WHERE id=? AND status='pending'",
                (interval, self._clock(), installation_id),
            )
            await db.commit()

    async def get_installation(self, installation_id: str) -> Installation | None:
        return await self._one_installation("id=?", (installation_id,))

    async def get_installation_by_session(self, session: str) -> Installation | None:
        return await self._one_installation("device_session=?", (session,))

    async def get_installation_by_app_id(self, app_id: str) -> Installation | None:
        return await self._one_installation("app_id=?", (app_id,))

    async def get_agent_installation(self, agent_id: str) -> Installation | None:
        return await self._one_installation(
            "agent_id=? ORDER BY updated_at DESC LIMIT 1", (agent_id,)
        )

    async def _one_installation(
        self, where: str, params: tuple[object, ...]
    ) -> Installation | None:
        sql = f"""SELECT id,agent_id,app_id,app_secret_ciphertext,installer_open_id,
        bot_open_id,status,device_session,verification_uri,error,created_at,updated_at,
        verification_uri_base,user_code,interval,expires_at,expires_in,tenant_key,
        tenant_name,bot_name,bot_avatar_url
        FROM installations WHERE {where}"""
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(sql, params)).fetchone()
        if row is None:
            return None
        installation = Installation(*row)
        if (
            installation.status == "pending"
            and installation.expires_at is not None
            and installation.expires_at <= self._clock()
        ):
            await self.mark_installation_error(installation.id, "expired")
            return Installation(
                **{
                    **installation.__dict__,
                    "status": "expired",
                    "error": "expired",
                    "updated_at": self._clock(),
                }
            )
        return installation

    async def delete_agent_installation(self, agent_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM installations WHERE agent_id=?", (agent_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def bind_thread(
        self,
        *,
        installation_id: str,
        chat_id: str,
        thread_id: str | None,
        agent_id: str,
        workspace_id: str | None,
        host_id: str | None = None,
        execution_mode: str = "auto",
        allowed_members: tuple[str, ...] | list[str] = (),
    ) -> ThreadBinding:
        now = self._clock()
        thread = thread_id or ""
        binding_id = uuid.uuid4().hex
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO thread_bindings
                (id,installation_id,chat_id,thread_id,agent_id,workspace_id,host_id,
                 execution_mode,allowed_members,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(installation_id,chat_id,thread_id) DO UPDATE SET
                 agent_id=excluded.agent_id,workspace_id=excluded.workspace_id,
                 host_id=excluded.host_id,execution_mode=excluded.execution_mode,
                 allowed_members=excluded.allowed_members,updated_at=excluded.updated_at""",
                (
                    binding_id,
                    installation_id,
                    chat_id,
                    thread,
                    agent_id,
                    workspace_id,
                    host_id,
                    execution_mode,
                    json.dumps(list(allowed_members)),
                    now,
                    now,
                ),
            )
            await db.commit()
        found = await self.get_binding(installation_id, chat_id, thread)
        assert found is not None
        return found

    async def get_binding(
        self, installation_id: str, chat_id: str, thread_id: str | None
    ) -> ThreadBinding | None:
        thread = thread_id or ""
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    """SELECT id,installation_id,chat_id,thread_id,agent_id,workspace_id,
                    run_id,host_id,execution_mode,allowed_members FROM thread_bindings
                    WHERE installation_id=? AND chat_id=? AND thread_id=?""",
                    (installation_id, chat_id, thread),
                )
            ).fetchone()
            if row is None and thread:
                row = await (
                    await db.execute(
                        """SELECT id,installation_id,chat_id,thread_id,agent_id,
                        workspace_id,run_id,host_id,execution_mode,allowed_members
                        FROM thread_bindings WHERE installation_id=? AND chat_id=?
                        AND thread_id=''""",
                        (installation_id, chat_id),
                    )
                ).fetchone()
        if row is None:
            return None
        values = list(row)
        values[-1] = tuple(json.loads(values[-1]))
        return ThreadBinding(*values)

    async def get_agent_binding(self, agent_id: str) -> ThreadBinding | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    """SELECT id,installation_id,chat_id,thread_id,agent_id,workspace_id,
                    run_id,host_id,execution_mode,allowed_members FROM thread_bindings
                    WHERE agent_id=? ORDER BY updated_at DESC,id DESC LIMIT 1""",
                    (agent_id,),
                )
            ).fetchone()
        if row is None:
            return None
        values = list(row)
        values[-1] = tuple(json.loads(values[-1]))
        return ThreadBinding(*values)

    async def set_binding_run(self, binding_id: str, run_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE thread_bindings SET run_id=?,updated_at=? WHERE id=?",
                (run_id, self._clock(), binding_id),
            )
            await db.commit()

    async def set_binding_workspace(self, binding_id: str, workspace_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE thread_bindings SET workspace_id=?,updated_at=? WHERE id=?",
                (workspace_id, self._clock(), binding_id),
            )
            await db.commit()

    async def claim_event(
        self, event_id: str, installation_id: str, sender_id: str | None
    ) -> tuple[bool, InboundEvent]:
        now = self._clock()
        async with aiosqlite.connect(self.path, isolation_level=None) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """INSERT OR IGNORE INTO inbound_events
                (event_id,installation_id,sender_id,status,created_at,updated_at)
                VALUES(?,?,?,'processing',?,?)""",
                (event_id, installation_id, sender_id, now, now),
            )
            row = await (
                await db.execute(
                    """SELECT event_id,installation_id,sender_id,status,run_id,error_code
                    FROM inbound_events WHERE event_id=?""",
                    (event_id,),
                )
            ).fetchone()
            await db.commit()
        assert row is not None
        return cursor.rowcount == 1, InboundEvent(*row)

    async def complete_event(self, event_id: str, run_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE inbound_events SET status='completed',run_id=?,error_code=NULL,
                updated_at=? WHERE event_id=?""",
                (run_id, self._clock(), event_id),
            )
            await db.commit()

    async def fail_event(self, event_id: str, error_code: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE inbound_events SET status='failed',error_code=?,updated_at=?
                WHERE event_id=?""",
                (error_code, self._clock(), event_id),
            )
            await db.commit()

    async def enqueue_notification(
        self,
        *,
        installation_id: str,
        payload: Mapping[str, object],
        run_id: str | None = None,
        event_id: str | None = None,
    ) -> Notification:
        now = self._clock()
        notification_id = uuid.uuid4().hex
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO notifications
                (id,installation_id,run_id,event_id,payload,status,next_attempt_at,created_at,updated_at)
                VALUES(?,?,?,?,?,'pending',?,?,?)""",
                (
                    notification_id,
                    installation_id,
                    run_id,
                    event_id,
                    json.dumps(payload, separators=(",", ":")),
                    now,
                    now,
                    now,
                ),
            )
            await db.commit()
        return (await self.get_notification_by_event(installation_id, event_id)) or Notification(
            notification_id,
            installation_id,
            run_id,
            event_id,
            json.dumps(payload),
            "pending",
            0,
            now,
            None,
        )

    async def get_notification_by_event(
        self, installation_id: str, event_id: str | None
    ) -> Notification | None:
        if event_id is None:
            return None
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    """SELECT id,installation_id,run_id,event_id,payload,status,
                    attempt_count,next_attempt_at,last_error FROM notifications
                    WHERE installation_id=? AND event_id=?""",
                    (installation_id, event_id),
                )
            ).fetchone()
        return Notification(*row) if row else None

    async def due_notifications(self, *, limit: int = 20) -> list[Notification]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (
                await db.execute(
                    """SELECT id,installation_id,run_id,event_id,payload,status,
                    attempt_count,next_attempt_at,last_error FROM notifications
                    WHERE status IN ('pending','retrying') AND next_attempt_at<=?
                    ORDER BY next_attempt_at LIMIT ?""",
                    (self._clock(), limit),
                )
            ).fetchall()
        return [Notification(*row) for row in rows]

    async def mark_notification_sent(self, notification_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE notifications SET status='sent',updated_at=? WHERE id=?",
                (self._clock(), notification_id),
            )
            await db.commit()

    async def retry_notification(self, notification_id: str, error: str) -> None:
        now = self._clock()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE notifications SET status='retrying',attempt_count=attempt_count+1,
                next_attempt_at=? + MIN(3600, 30 * (attempt_count + 1)),last_error=?,updated_at=?
                WHERE id=?""",
                (now, error, now, notification_id),
            )
            await db.commit()

    async def get_surface(self, installation_id: str) -> Mapping[str, object] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (
                await db.execute(
                    "SELECT * FROM surfaces WHERE installation_id=?", (installation_id,)
                )
            ).fetchone()
        return dict(row) if row else None

    async def save_surface(self, installation_id: str, values: Mapping[str, object]) -> None:
        now = self._clock()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO surfaces
                (installation_id,surface_profile_id,surface_version,status,surface_type,error,
                 last_provisioned_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(installation_id) DO UPDATE SET
                 surface_profile_id=excluded.surface_profile_id,
                 surface_version=excluded.surface_version,status=excluded.status,
                 surface_type=excluded.surface_type,error=excluded.error,
                 last_provisioned_at=excluded.last_provisioned_at,updated_at=excluded.updated_at""",
                (
                    installation_id,
                    values["surface_profile_id"],
                    values["surface_version"],
                    values["status"],
                    values["surface_type"],
                    values.get("error"),
                    values["last_provisioned_at"],
                    now,
                ),
            )
            await db.commit()


SQLiteStore = FeishuStore

__all__ = ["FeishuStore", "SQLiteStore"]
