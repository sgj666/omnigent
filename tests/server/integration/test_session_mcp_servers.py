"""Integration tests for session MCP server management routes."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
import yaml

from omnigent.server.bundles import bundle_location
from omnigent.server.routes import session_mcp_servers as mcp_routes
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from tests.server.helpers import create_test_session

pytestmark = pytest.mark.asyncio


async def test_list_mcp_servers_uses_pinned_bundle_after_agent_update(
    client: httpx.AsyncClient,
    db_uri: str,
    tmp_path: Path,
) -> None:
    """GET reads the Session snapshot instead of the mutable Agent bundle."""
    bundle_a = _single_yaml_bundle(
        """\
spec_version: 1
name: pinned-mcp-agent
executor:
  config:
    harness: claude-sdk
""",
        filename="config.yaml",
    )
    created = await client.post(
        "/v1/sessions",
        data={"metadata": "{}"},
        files={"bundle": ("agent.tar.gz", bundle_a, "application/gzip")},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    created_agent_id = created.json()["agent_id"]

    bundle_b = _single_yaml_bundle(
        """\
spec_version: 1
name: pinned-mcp-agent
executor:
  config:
    harness: claude-sdk
tools:
  mutable-only:
    type: mcp
    transport: http
    url: https://example.com/mutable
""",
        filename="config.yaml",
    )
    location_b = bundle_location(created_agent_id, bundle_b)
    LocalArtifactStore(str(tmp_path / "artifacts")).put(location_b, bundle_b)
    updated = SqlAlchemyAgentStore(db_uri).update(created_agent_id, location_b)
    assert updated is not None and updated.version == 2

    response = await client.get(f"/v1/sessions/{session_id}/agent/mcp-servers")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == []


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        (
            "POST",
            "",
            {
                "name": "new-server",
                "transport": "http",
                "url": "https://example.com/new",
            },
        ),
        (
            "PUT",
            "/existing",
            {
                "name": "renamed",
                "transport": "http",
                "url": "https://example.com/renamed",
            },
        ),
        ("DELETE", "/existing", None),
    ],
    ids=["post", "put", "delete"],
)
async def test_pinned_session_rejects_mcp_mutation_before_side_effects(
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    suffix: str,
    payload: dict[str, Any] | None,
) -> None:
    """Pinned Session MCP declarations are immutable in place."""
    bundle = _single_yaml_bundle(
        """\
spec_version: 1
name: pinned-mcp-write
executor:
  config:
    harness: claude-sdk
tools:
  existing:
    type: mcp
    transport: http
    url: https://example.com/existing
""",
        filename="config.yaml",
    )
    created = await client.post(
        "/v1/sessions",
        data={"metadata": "{}"},
        files={"bundle": ("agent.tar.gz", bundle, "application/gzip")},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    agent_id = created.json()["agent_id"]
    before = SqlAlchemyAgentStore(db_uri).get(agent_id)
    assert before is not None
    side_effects: list[str] = []

    async def _reset(*args: object, **kwargs: object) -> None:
        del args, kwargs
        side_effects.append("cache-reset")

    def _publish(*args: object, **kwargs: object) -> None:
        del args, kwargs
        side_effects.append("sse")

    monkeypatch.setattr(mcp_routes, "_reset_runner_session_agent_cache", _reset)
    monkeypatch.setattr(mcp_routes, "_publish_agent_changed", _publish)

    response = await client.request(
        method,
        f"/v1/sessions/{session_id}/agent/mcp-servers{suffix}",
        json=payload,
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert SqlAlchemyAgentStore(db_uri).get(agent_id) == before
    assert side_effects == []


async def test_partial_snapshot_rejects_mcp_write_before_agent_read(
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial Session pin fails before mutable Agent lookup or mutation."""
    session = await create_test_session(client, name="mcp-partial-snapshot")
    session_id = session["id"]
    engine = sa.create_engine(db_uri)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE conversations SET agent_bundle_digest = NULL WHERE id = :id"),
                {"id": bytes.fromhex(session_id)},
            )
    finally:
        engine.dispose()
    reads: list[str] = []
    original_get = SqlAlchemyAgentStore.get

    def _get(store: SqlAlchemyAgentStore, agent_id: str):
        reads.append(agent_id)
        return original_get(store, agent_id)

    monkeypatch.setattr(SqlAlchemyAgentStore, "get", _get)

    response = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={
            "name": "blocked",
            "transport": "http",
            "url": "https://example.com/blocked",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert reads == []


async def test_legacy_all_null_session_mcp_mutation_remains_editable(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Legacy Sessions without a snapshot retain mutable MCP compatibility."""
    session = await create_test_session(client, name="mcp-legacy-edit")
    _clear_agent_snapshot(db_uri, session["id"])

    response = await client.post(
        f"/v1/sessions/{session['id']}/agent/mcp-servers",
        json={
            "name": "legacy-server",
            "transport": "http",
            "url": "https://example.com/legacy",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "legacy-server"


async def test_create_mcp_server_updates_agent_bundle(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """POST creates an MCP YAML file and the session agent reports it."""
    session = await _create_legacy_session(client, db_uri, name="mcp-agent")
    session_id = session["id"]

    resp = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={
            "name": "github",
            "transport": "http",
            "url": "https://example.com/sse",
            "description": "GitHub tools",
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "name": "github",
        "transport": "http",
        "description": "GitHub tools",
        "url": "https://example.com/sse",
        "headers": {},
        "command": None,
        "args": [],
    }

    agent_resp = await client.get(f"/v1/sessions/{session_id}/agent")
    assert agent_resp.status_code == 200, agent_resp.text
    assert agent_resp.json()["mcp_servers"] == [resp.json()]
    assert _mcp_file_from_bundle(
        await _agent_bundle(client, session_id),
        "github.yaml",
    ) == {
        "name": "github",
        "transport": "http",
        "description": "GitHub tools",
        "url": "https://example.com/sse",
    }


async def test_mcp_server_mutations_reset_bound_runner_agent_cache(
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP server mutations invalidate stale runner-side agent caches."""
    calls: list[tuple[str, str, object]] = []

    async def _fake_reset(
        session_id: str,
        agent_id: str,
        runner_router: object,
    ) -> None:
        calls.append((session_id, agent_id, runner_router))

    monkeypatch.setattr(mcp_routes, "_reset_runner_session_agent_cache", _fake_reset)
    session = await _create_legacy_session(client, db_uri, name="mcp-reset-agent")
    session_id = session["id"]

    resp = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={
            "name": "echo",
            "transport": "stdio",
            "command": "python",
            "args": ["echo_server.py"],
        },
    )

    assert resp.status_code == 200, resp.text

    update = await client.put(
        f"/v1/sessions/{session_id}/agent/mcp-servers/echo",
        json={
            "name": "echo-renamed",
            "transport": "stdio",
            "command": "python",
            "args": ["echo_server.py"],
        },
    )
    assert update.status_code == 200, update.text

    delete = await client.delete(f"/v1/sessions/{session_id}/agent/mcp-servers/echo-renamed")
    assert delete.status_code == 204, delete.text

    assert [(sid, aid) for sid, aid, _ in calls] == [
        (session_id, session["agent_id"]),
        (session_id, session["agent_id"]),
        (session_id, session["agent_id"]),
    ]
    assert all(runner_router is not None for _, _, runner_router in calls)


async def test_update_mcp_server_can_rename_and_change_transport(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """PUT replaces the existing declaration and validates transport fields."""
    session = await _create_legacy_session(client, db_uri, name="mcp-update-agent")
    session_id = session["id"]
    create = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={"name": "search", "transport": "http", "url": "https://example.com/sse"},
    )
    assert create.status_code == 200, create.text

    update = await client.put(
        f"/v1/sessions/{session_id}/agent/mcp-servers/search",
        json={
            "name": "local-search",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-search"],
        },
    )

    assert update.status_code == 200, update.text
    assert update.json() == {
        "name": "local-search",
        "transport": "stdio",
        "description": None,
        "url": None,
        "headers": {},
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-search"],
    }
    agent_resp = await client.get(f"/v1/sessions/{session_id}/agent")
    assert [server["name"] for server in agent_resp.json()["mcp_servers"]] == ["local-search"]


async def test_delete_mcp_server_removes_it_from_agent(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """DELETE removes the MCP declaration from the stored bundle."""
    session = await _create_legacy_session(client, db_uri, name="mcp-delete-agent")
    session_id = session["id"]
    create = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={"name": "github", "transport": "http", "url": "https://example.com/sse"},
    )
    assert create.status_code == 200, create.text

    delete = await client.delete(f"/v1/sessions/{session_id}/agent/mcp-servers/github")

    assert delete.status_code == 204, delete.text
    agent_resp = await client.get(f"/v1/sessions/{session_id}/agent")
    assert agent_resp.status_code == 200, agent_resp.text
    assert agent_resp.json()["mcp_servers"] == []


async def test_create_mcp_server_rejects_duplicate_name(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Creating the same MCP server twice returns 409."""
    session = await _create_legacy_session(client, db_uri, name="mcp-dup-agent")
    session_id = session["id"]
    payload = {"name": "github", "transport": "http", "url": "https://example.com/sse"}
    first = await client.post(f"/v1/sessions/{session_id}/agent/mcp-servers", json=payload)
    assert first.status_code == 200, first.text

    second = await client.post(f"/v1/sessions/{session_id}/agent/mcp-servers", json=payload)

    assert second.status_code == 409, second.text


async def test_create_mcp_server_supports_single_yaml_bundle(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Single-file omnigent YAML bundles are updated inline."""
    create_session = await client.post(
        "/v1/sessions",
        data={"metadata": "{}"},
        files={
            "bundle": (
                "agent.tar.gz",
                _single_yaml_bundle(
                    """\
name: single_yaml_agent
prompt: Say hello.
executor:
  model: gpt-4o-mini
  harness: openai-agents
"""
                ),
                "application/gzip",
            )
        },
    )
    assert create_session.status_code == 201, create_session.text
    session_id = create_session.json()["session_id"]
    _clear_agent_snapshot(db_uri, session_id)

    resp = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={"name": "browser-search", "transport": "http", "url": "https://example.com/sse"},
    )

    assert resp.status_code == 200, resp.text
    agent_resp = await client.get(f"/v1/sessions/{session_id}/agent")
    assert [server["name"] for server in agent_resp.json()["mcp_servers"]] == ["browser-search"]


async def test_update_mcp_server_preserves_headers_on_redacted_roundtrip(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Editing a server while sending [REDACTED] header values must not overwrite secrets."""
    session = await _create_legacy_session(client, db_uri, name="mcp-headers-agent")
    session_id = session["id"]

    # Create server with a real Authorization header.
    create = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={
            "name": "secure",
            "transport": "http",
            "url": "https://example.com/sse",
            "headers": {"Authorization": "Bearer real-token"},
        },
    )
    assert create.status_code == 200, create.text

    # Simulate the UI round-trip: the GET returns [REDACTED] values; the client
    # sends them back verbatim when editing only the URL.
    update = await client.put(
        f"/v1/sessions/{session_id}/agent/mcp-servers/secure",
        json={
            "name": "secure",
            "transport": "http",
            "url": "https://example.com/sse-v2",
            "headers": {"Authorization": "[REDACTED]"},
        },
    )
    assert update.status_code == 200, update.text

    # The bundle must still contain the real token, not the sentinel.
    bundle = await _agent_bundle(client, session_id)
    mcp_file = _mcp_file_from_bundle(bundle, "secure.yaml")
    assert mcp_file["url"] == "https://example.com/sse-v2"
    assert mcp_file.get("headers") == {"Authorization": "Bearer real-token"}


async def test_update_mcp_server_clears_headers_when_empty_dict_sent(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Sending headers={} on update must remove all headers from the bundle."""
    session = await _create_legacy_session(client, db_uri, name="mcp-clear-headers-agent")
    session_id = session["id"]

    create = await client.post(
        f"/v1/sessions/{session_id}/agent/mcp-servers",
        json={
            "name": "secure",
            "transport": "http",
            "url": "https://example.com/sse",
            "headers": {"Authorization": "Bearer real-token"},
        },
    )
    assert create.status_code == 200, create.text

    # User removes all header rows — client sends {}.
    update = await client.put(
        f"/v1/sessions/{session_id}/agent/mcp-servers/secure",
        json={
            "name": "secure",
            "transport": "http",
            "url": "https://example.com/sse",
            "headers": {},
        },
    )
    assert update.status_code == 200, update.text
    assert update.json()["headers"] == {}

    bundle = await _agent_bundle(client, session_id)
    mcp_file = _mcp_file_from_bundle(bundle, "secure.yaml")
    assert "headers" not in mcp_file


async def _agent_bundle(client: httpx.AsyncClient, session_id: str) -> bytes:
    """Download the session agent bundle."""
    resp = await client.get(f"/v1/sessions/{session_id}/agent/contents")
    assert resp.status_code == 200, resp.text
    return resp.content


async def _create_legacy_session(
    client: httpx.AsyncClient,
    db_uri: str,
    *,
    name: str,
) -> dict[str, Any]:
    """Create a Session and explicitly opt the test into legacy mutability."""
    session = await create_test_session(client, name=name)
    _clear_agent_snapshot(db_uri, session["id"])
    return session


def _clear_agent_snapshot(db_uri: str, session_id: str) -> None:
    """Convert one test Session to the three-NULL legacy representation."""
    engine = sa.create_engine(db_uri)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE conversations SET agent_bundle_version = NULL, "
                    "agent_bundle_digest = NULL, agent_bundle_location = NULL "
                    "WHERE id = :id"
                ),
                {"id": bytes.fromhex(session_id)},
            )
    finally:
        engine.dispose()


def _mcp_file_from_bundle(bundle: bytes, filename: str) -> dict[str, Any]:
    """Read one MCP YAML file from a bundle by basename."""
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith(f"/tools/mcp/{filename}"))
        extracted = tf.extractfile(member)
        assert extracted is not None
        data = yaml.safe_load(extracted.read())
    assert isinstance(data, dict)
    return data


def _single_yaml_bundle(yaml_text: str, *, filename: str = "agent.yaml") -> bytes:
    """Build a tar.gz bundle containing one omnigent YAML file."""
    buf = io.BytesIO()
    data = yaml_text.encode()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=filename)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()
