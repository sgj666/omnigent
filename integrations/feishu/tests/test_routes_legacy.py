from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from omnigent_feishu.credentials import FeishuCredentialCipher
from omnigent_feishu.device_flow import FeishuDeviceSession
from omnigent_feishu.legacy_import import LegacyImporter
from omnigent_feishu.routes import create_feishu_router
from omnigent_feishu.store import FeishuStore


class Device:
    async def begin(self):
        return FeishuDeviceSession("session", "https://qr", 3, 120)


class Adapter:
    async def receive(self, *_args, **_kwargs):
        raise AssertionError("not called")


def test_installation_routes_are_agent_scoped_and_keep_qr(tmp_path) -> None:
    store = FeishuStore(tmp_path / "provider.db")
    asyncio.run(store.initialize())
    asyncio.run(
        store.set_agent_default_scope("ag_polly", workspace="/tmp/workspace", host_id="local")
    )
    app = FastAPI()
    app.include_router(
        create_feishu_router(
            store,
            Device(),
            FeishuCredentialCipher("credential-secret"),
            Adapter(),
        )
    )
    with TestClient(app) as client:
        response = client.post("/v1/agents/ag_polly/feishu/installations")
        assert response.status_code == 201
        assert response.json()["agent_id"] == "ag_polly"
        assert response.json()["verification_uri_complete"] == "https://qr"
        assert client.post("/v1/teams/team/feishu/install/begin").status_code == 404


@pytest.mark.asyncio
async def test_legacy_import_is_repeatable_and_read_only(tmp_path) -> None:
    legacy = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy)
    connection.execute(
        """CREATE TABLE feishu_installations
        (id TEXT, team_id TEXT, agent_id TEXT, app_id TEXT,
         app_secret_ciphertext BLOB, installer_open_id TEXT,
         bot_open_id TEXT, created_at INTEGER)"""
    )
    connection.execute(
        "INSERT INTO feishu_installations VALUES(?,?,?,?,?,?,?,?)",
        ("fi", "team", "ag", "cli", b"ciphertext", "ou", "bot", 1),
    )
    connection.commit()
    connection.close()
    store = FeishuStore(tmp_path / "provider.db")
    importer = LegacyImporter(legacy, store)
    first = await importer.run()
    second = await importer.run()
    assert first.imported == 1
    assert second.imported == 0
    check = sqlite3.connect(legacy)
    assert check.execute("SELECT COUNT(*) FROM feishu_installations").fetchone()[0] == 1
    check.close()
