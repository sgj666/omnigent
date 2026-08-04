"""Repeatable one-time import from read-only legacy Core Feishu tables."""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from omnigent_feishu.config import FeishuConfig
from omnigent_feishu.store import FeishuStore

AgentResolver = Callable[[str], Awaitable[list[str]]]


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped: int
    needs_reconnect: tuple[str, ...]
    dry_run: bool = False


class LegacyImporter:
    """Reads legacy rows without modifying them and never enables dual writes."""

    def __init__(
        self,
        legacy_path: str | Path,
        store: FeishuStore,
        *,
        resolve_team_agents: AgentResolver | None = None,
    ) -> None:
        self._legacy_path = Path(legacy_path)
        self._store = store
        self._resolve = resolve_team_agents

    async def run(self, *, dry_run: bool = False) -> ImportResult:
        await self._store.initialize()
        if await self._store.get_meta("legacy_feishu_import_complete") == "1":
            return ImportResult(0, 0, (), dry_run)
        rows = await self._rows()
        imported = 0
        skipped = 0
        reconnect: list[str] = []
        for row in rows:
            agent_id = row.get("agent_id")
            team_id = str(row.get("team_id") or "")
            if not agent_id and team_id and self._resolve is not None:
                candidates = await self._resolve(team_id)
                agent_id = candidates[0] if len(candidates) == 1 else None
            if not isinstance(agent_id, str) or not agent_id:
                reconnect.append(team_id or str(row.get("id")))
                continue
            ciphertext = row.get("app_secret_ciphertext")
            if isinstance(ciphertext, bytes):
                try:
                    ciphertext = ciphertext.decode("ascii")
                except UnicodeDecodeError:
                    ciphertext = base64.urlsafe_b64encode(ciphertext).decode("ascii")
            if not isinstance(ciphertext, str):
                skipped += 1
                continue
            if dry_run:
                imported += 1
                continue
            added = await self._store.import_installation(
                installation_id=str(row["id"]),
                agent_id=agent_id,
                app_id=str(row["app_id"]),
                app_secret_ciphertext=ciphertext,
                installer_open_id=row.get("installer_open_id"),
                bot_open_id=row.get("bot_open_id"),
                created_at=int(row.get("created_at") or 0),
            )
            imported += int(added)
            skipped += int(not added)
        if not dry_run:
            await self._store.set_meta("legacy_feishu_import_complete", "1")
        return ImportResult(imported, skipped, tuple(sorted(set(reconnect))), dry_run)

    async def _rows(self) -> list[dict[str, object]]:
        uri = f"file:{self._legacy_path}?mode=ro"
        try:
            async with aiosqlite.connect(uri, uri=True) as db:
                db.row_factory = aiosqlite.Row
                exists = await (
                    await db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='feishu_installations'"
                    )
                ).fetchone()
                if not exists:
                    return []
                rows = await (await db.execute("SELECT * FROM feishu_installations")).fetchall()
        except aiosqlite.Error:
            return []
        return [dict(row) for row in rows]


def _legacy_path() -> Path:
    value = os.environ.get("OMNIGENT_LEGACY_DATABASE_PATH")
    if not value:
        raise SystemExit("OMNIGENT_LEGACY_DATABASE_PATH is required")
    return Path(value).expanduser()


async def _run(dry_run: bool) -> None:
    config = FeishuConfig()
    result = await LegacyImporter(_legacy_path(), FeishuStore(config.database_path)).run(
        dry_run=dry_run
    )
    print(
        f"imported={result.imported} skipped={result.skipped} "
        f"needs_reconnect={len(result.needs_reconnect)} dry_run={result.dry_run}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy Feishu installations once")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    main()


__all__ = ["ImportResult", "LegacyImporter", "main"]
