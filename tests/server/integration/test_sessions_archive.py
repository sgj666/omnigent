"""Integration tests for session archive lifecycle and agent contents download.

Covers:
- ``PATCH /v1/sessions/{id}`` with ``archived=True/False``
- ``GET /v1/sessions`` with ``include_archived`` filtering
- ``GET /v1/sessions/{id}/agent/contents`` returning a valid gzip tarball

Uses the shared ``client`` fixture from ``tests/server/conftest.py``
(real stores + mock LLM) so the tests hit the real route-to-store
pipeline without subprocesses.
"""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import sqlalchemy as sa

from omnigent.db.utils import generate_agent_id
from omnigent.server.bundles import bundle_location
from omnigent.server.routes import sessions as sessions_module
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import (
    SqlAlchemyConversationStore,
)
from tests.server.helpers import build_agent_bundle, create_test_session

pytestmark = pytest.mark.asyncio


# ── Archive / unarchive lifecycle ────────────────────────


async def test_session_not_archived_by_default(
    client: httpx.AsyncClient,
) -> None:
    """A freshly created session has ``archived=False``."""
    session = await create_test_session(client, name="archive-default")
    assert session["archived"] is False


async def test_archive_hides_session_from_default_listing(
    client: httpx.AsyncClient,
) -> None:
    """Archiving a session removes it from the default GET /v1/sessions listing."""
    session = await create_test_session(client, name="archive-hide")
    session_id = session["id"]

    # Archive it.
    patch_resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"archived": True},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["archived"] is True

    # Default listing (include_archived=False) should not contain it.
    listing = await client.get("/v1/sessions")
    assert listing.status_code == 200
    listed_ids = [s["id"] for s in listing.json()["data"]]
    assert session_id not in listed_ids


async def test_archived_session_appears_with_include_archived(
    client: httpx.AsyncClient,
) -> None:
    """An archived session is returned when ``include_archived=True``."""
    session = await create_test_session(client, name="archive-include")
    session_id = session["id"]

    await client.patch(
        f"/v1/sessions/{session_id}",
        json={"archived": True},
    )

    listing = await client.get("/v1/sessions", params={"include_archived": "true"})
    assert listing.status_code == 200
    listed_ids = [s["id"] for s in listing.json()["data"]]
    assert session_id in listed_ids


async def test_unarchive_restores_session_to_default_listing(
    client: httpx.AsyncClient,
) -> None:
    """Unarchiving a session makes it visible in the default listing again."""
    session = await create_test_session(client, name="archive-restore")
    session_id = session["id"]

    # Archive then unarchive.
    await client.patch(f"/v1/sessions/{session_id}", json={"archived": True})
    patch_resp = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"archived": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["archived"] is False

    # Back in the default listing.
    listing = await client.get("/v1/sessions")
    assert listing.status_code == 200
    listed_ids = [s["id"] for s in listing.json()["data"]]
    assert session_id in listed_ids


# ── Best-effort stop before archive ───────────────────────


async def test_archive_running_session_attempts_stop(
    client: httpx.AsyncClient,
) -> None:
    """Archiving a running session calls ``_stop_session_via_runner``."""
    session = await create_test_session(client, name="archive-running")
    session_id = session["id"]

    mock_stop = AsyncMock(return_value=True)
    sessions_module._session_status_cache[session_id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.patch(
                f"/v1/sessions/{session_id}",
                json={"archived": True},
            )
        assert resp.status_code == 200
        assert resp.json()["archived"] is True
        mock_stop.assert_awaited_once()
    finally:
        sessions_module._session_status_cache.pop(session_id, None)


async def test_archive_idle_parent_stops_running_child(
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Archiving an idle parent with a running child stops the child.

    Regression test: ``_best_effort_stop`` previously used the child
    rollup only to decide whether to act, then always issued the stop
    against the parent's own session id. A parent that has already gone
    idle while its sub-agent child keeps running would get a no-op stop,
    leaving the child orphaned once the parent (and its DB row, via the
    cascading subtree delete/archive) is gone.
    """
    session = await create_test_session(client, name="archive-idle-parent-child")
    session_id = session["id"]

    conv_store = SqlAlchemyConversationStore(db_uri)
    child = conv_store.create_conversation(
        kind="sub_agent",
        title="researcher:auth",
        parent_conversation_id=session_id,
        agent_id=session["agent_id"],
    )

    mock_stop = AsyncMock(return_value=True)
    sessions_module._session_status_cache[child.id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.patch(
                f"/v1/sessions/{session_id}",
                json={"archived": True},
            )
        assert resp.status_code == 200
        assert resp.json()["archived"] is True
        # The child must be the one stopped, not the (idle) parent.
        mock_stop.assert_awaited_once()
        assert mock_stop.await_args is not None
        assert mock_stop.await_args.args[0] == child.id
    finally:
        sessions_module._session_status_cache.pop(child.id, None)


async def test_archive_proceeds_when_stop_fails(
    client: httpx.AsyncClient,
) -> None:
    """Archive succeeds even when the runner stop raises."""
    session = await create_test_session(client, name="archive-stop-fail")
    session_id = session["id"]

    mock_stop = AsyncMock(side_effect=ConnectionError("runner gone"))
    sessions_module._session_status_cache[session_id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.patch(
                f"/v1/sessions/{session_id}",
                json={"archived": True},
            )
        assert resp.status_code == 200
        assert resp.json()["archived"] is True
    finally:
        sessions_module._session_status_cache.pop(session_id, None)


async def test_archive_proceeds_when_child_lookup_fails(
    client: httpx.AsyncClient,
) -> None:
    """Archive succeeds even when the child-id DB lookup raises."""
    session = await create_test_session(client, name="archive-db-fail")
    session_id = session["id"]

    sessions_module._session_status_cache[session_id] = "running"
    try:
        with patch.object(
            sessions_module,
            "_best_effort_stop",
            wraps=sessions_module._best_effort_stop,
        ):
            orig = sessions_module._best_effort_stop

            async def _patched_stop(sid, cs, rr):
                with patch.object(
                    cs,
                    "list_child_conversation_ids_by_parent",
                    side_effect=RuntimeError("transient DB error"),
                ):
                    await orig(sid, cs, rr)

            with patch.object(sessions_module, "_best_effort_stop", _patched_stop):
                resp = await client.patch(
                    f"/v1/sessions/{session_id}",
                    json={"archived": True},
                )
        assert resp.status_code == 200
        assert resp.json()["archived"] is True
    finally:
        sessions_module._session_status_cache.pop(session_id, None)


async def test_archive_idle_session(
    client: httpx.AsyncClient,
) -> None:
    """An idle session can be archived normally (no stop needed)."""
    session = await create_test_session(client, name="archive-idle")
    session_id = session["id"]

    mock_stop = AsyncMock()
    with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
        resp = await client.patch(
            f"/v1/sessions/{session_id}",
            json={"archived": True},
        )
    assert resp.status_code == 200
    assert resp.json()["archived"] is True
    mock_stop.assert_not_awaited()


async def test_unarchive_skips_stop(
    client: httpx.AsyncClient,
) -> None:
    """Unarchiving does not attempt a stop, even if the session is running."""
    session = await create_test_session(client, name="unarchive-running")
    session_id = session["id"]

    await client.patch(f"/v1/sessions/{session_id}", json={"archived": True})

    mock_stop = AsyncMock()
    sessions_module._session_status_cache[session_id] = "running"
    try:
        with patch.object(sessions_module, "_stop_session_via_runner", mock_stop):
            resp = await client.patch(
                f"/v1/sessions/{session_id}",
                json={"archived": False},
            )
        assert resp.status_code == 200
        assert resp.json()["archived"] is False
        mock_stop.assert_not_awaited()
    finally:
        sessions_module._session_status_cache.pop(session_id, None)


# ── Agent contents download ──────────────────────────────


async def test_agent_contents_returns_valid_gzip_tarball(
    client: httpx.AsyncClient,
) -> None:
    """GET /v1/sessions/{id}/agent/contents returns a valid tar.gz bundle."""
    session = await create_test_session(client, name="contents-download")
    session_id = session["id"]

    resp = await client.get(f"/v1/sessions/{session_id}/agent/contents")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"

    # Verify the bytes are valid gzip.
    decompressed = gzip.decompress(resp.content)
    assert len(decompressed) > 0

    # Verify the bytes are a valid tar archive containing config.yaml.
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
        names = tf.getnames()
        assert "config.yaml" in names


async def test_agent_contents_404_for_nonexistent_session(
    client: httpx.AsyncClient,
) -> None:
    """GET /v1/sessions/{id}/agent/contents returns 404 for a missing session."""
    resp = await client.get("/v1/sessions/conv_nonexistent/agent/contents")
    assert resp.status_code == 404


async def test_agent_contents_rejects_partial_snapshot_before_store_reads(
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt pin fails closed before mutable Agent or artifact lookup."""
    session = await create_test_session(client, name="contents-partial-snapshot")
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

    agent_reads: list[str] = []
    artifact_reads: list[str] = []
    original_agent_get = SqlAlchemyAgentStore.get
    original_artifact_get = LocalArtifactStore.get

    def _agent_get(store: SqlAlchemyAgentStore, agent_id: str):
        agent_reads.append(agent_id)
        return original_agent_get(store, agent_id)

    def _artifact_get(store: LocalArtifactStore, key: str) -> bytes:
        artifact_reads.append(key)
        return original_artifact_get(store, key)

    monkeypatch.setattr(SqlAlchemyAgentStore, "get", _agent_get)
    monkeypatch.setattr(LocalArtifactStore, "get", _artifact_get)

    response = await client.get(f"/v1/sessions/{session_id}/agent/contents")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert agent_reads == []
    assert artifact_reads == []


async def test_agent_contents_rejects_tampered_pinned_bundle(
    client: httpx.AsyncClient,
    db_uri: str,
    tmp_path: Path,
) -> None:
    """Bytes at a pinned content-addressed key must match its SHA-256 digest."""
    session = await create_test_session(client, name="contents-tampered-bundle")
    session_id = session["id"]
    conversation = SqlAlchemyConversationStore(db_uri).get_conversation(session_id)
    assert conversation is not None
    assert conversation.agent_bundle_location is not None
    LocalArtifactStore(str(tmp_path / "artifacts")).put(
        conversation.agent_bundle_location,
        b"tampered bundle bytes",
    )

    response = await client.get(f"/v1/sessions/{session_id}/agent/contents")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"


async def test_pinned_session_agent_routes_keep_original_bundle_after_agent_update(
    client: httpx.AsyncClient,
    db_uri: str,
    tmp_path: Path,
) -> None:
    """Contents, metadata, and PUT honor the Conversation's immutable pin."""
    agent_id = generate_agent_id()
    bundle_a = build_agent_bundle(name="pinned-template")
    bundle_b = build_agent_bundle(
        name="pinned-template",
        executor={"type": "omnigent", "config": {"harness": "codex-native"}},
    )
    location_a = bundle_location(agent_id, bundle_a)
    location_b = bundle_location(agent_id, bundle_b)
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    artifact_store.put(location_a, bundle_a)
    agent_store = SqlAlchemyAgentStore(db_uri)
    agent_store.create(agent_id, name="pinned-template", bundle_location=location_a)

    created = await client.post("/v1/sessions", json={"agent_id": agent_id})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    artifact_store.put(location_b, bundle_b)
    updated = agent_store.update(agent_id, location_b)
    assert updated is not None and updated.version == 2

    contents = await client.get(f"/v1/sessions/{session_id}/agent/contents")
    assert contents.status_code == 200, contents.text
    assert contents.content == bundle_a
    assert contents.headers["X-Agent-Version"] == "1"
    metadata = await client.get(f"/v1/sessions/{session_id}/agent")
    assert metadata.status_code == 200, metadata.text
    assert metadata.json()["version"] == 1
    assert metadata.json()["harness"] == "claude-sdk"

    rejected = await client.put(
        f"/v1/sessions/{session_id}/agent",
        files={"bundle": ("agent.tar.gz", bundle_b, "application/gzip")},
    )
    assert rejected.status_code == 409, rejected.text
    assert agent_store.get(agent_id) == updated


async def test_multipart_child_agent_contents_use_parent_pinned_bundle(
    client: httpx.AsyncClient,
) -> None:
    """A multipart child serves its Parent snapshot, not its own mutable Agent row."""
    bundle_a = build_agent_bundle(name="pinned-parent")
    parent = await client.post(
        "/v1/sessions",
        data={"metadata": "{}"},
        files={"bundle": ("parent.tar.gz", bundle_a, "application/gzip")},
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["session_id"]
    bundle_b = build_agent_bundle(name="multipart-child")
    child = await client.post(
        "/v1/sessions",
        data={"metadata": json.dumps({"parent_session_id": parent_id})},
        files={"bundle": ("child.tar.gz", bundle_b, "application/gzip")},
    )
    assert child.status_code == 201, child.text

    contents = await client.get(f"/v1/sessions/{child.json()['session_id']}/agent/contents")
    assert contents.status_code == 200, contents.text
    assert contents.content == bundle_a
    assert contents.headers["X-Agent-Version"] == "1"
