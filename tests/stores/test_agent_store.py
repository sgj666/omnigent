"""Tests for SqlAlchemyAgentStore."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from pathlib import Path
from threading import Barrier, Event, RLock

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

import omnigent.stores.agent_store.sqlalchemy_store as agent_store_sqlalchemy
from omnigent.db.db_models import workspace_scope
from omnigent.db.utils import get_or_create_engine
from omnigent.stores.agent_store import AgentVersionConflict
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore


def test_create_and_get(agent_store: SqlAlchemyAgentStore) -> None:
    agent = agent_store.create(
        agent_id="88089a8b5dd4eb29fe17d41b2b028cfa",
        name="gpt-4",
        bundle_location="ag_test_gpt4/fakehash",
    )
    assert len(agent.id) == 32
    assert agent.name == "gpt-4"

    fetched = agent_store.get(agent.id)
    assert fetched is not None
    assert fetched.id == agent.id
    assert fetched.name == "gpt-4"


def test_get_nonexistent(agent_store: SqlAlchemyAgentStore) -> None:
    assert agent_store.get("5ff5b2e31fe10beb80134394037b17b0") is None


def test_session_scoped_agent_resolves_to_spawn_tree_root(
    agent_store: SqlAlchemyAgentStore,
    db_uri: str,
) -> None:
    """A shared child agent always authorizes against the stable tree root."""
    root_id = "1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a"
    child_id = "2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b"
    agent_id = "3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c"
    engine = get_or_create_engine(db_uri)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conversations "
                "(id, created_at, updated_at, root_conversation_id, agent_id) "
                "VALUES (:id, :ts, :ts, :root_id, :agent_id)"
            ),
            {
                "id": bytes.fromhex(root_id),
                "ts": 1700000000,
                "root_id": bytes.fromhex(root_id),
                "agent_id": bytes.fromhex(agent_id),
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO conversations "
                "(id, created_at, updated_at, parent_conversation_id, "
                "root_conversation_id, agent_id) "
                "VALUES (:id, :ts, :ts, :root_id, :root_id, :agent_id)"
            ),
            {
                "id": bytes.fromhex(child_id),
                "ts": 1700000001,
                "root_id": bytes.fromhex(root_id),
                "agent_id": bytes.fromhex(agent_id),
            },
        )

    assert agent_store._session_id_for_agent(agent_id) == root_id


def test_get_by_name(agent_store: SqlAlchemyAgentStore) -> None:
    agent_store.create(
        agent_id="d949d15d8243d399d68ce236abee269d",
        name="claude",
        bundle_location="ag_test_claude/fakehash",
    )
    found = agent_store.get_by_name("claude")
    assert found is not None
    assert found.name == "claude"
    assert agent_store.get_by_name("missing") is None


def test_create_rejects_duplicate_template_name(agent_store: SqlAlchemyAgentStore) -> None:
    """Template names are unique within a workspace, enforced by the store.

    The DB has no partial unique index (MySQL can't build one), so the store's
    create() is the guard.
    """
    agent_store.create(
        agent_id="7881b57b13260d58fd37b103ee69db65",
        name="dup-name",
        bundle_location="ag_dup_a/fakehash",
    )
    with pytest.raises(IntegrityError):
        agent_store.create(
            agent_id="d924ef7a50570dbbf38c67b059afc7ef",
            name="dup-name",
            bundle_location="ag_dup_b/fakehash",
        )


def test_get_by_name_and_list_hide_session_scoped_agents(
    agent_store: SqlAlchemyAgentStore,
    db_uri: str,
) -> None:
    """Public agent lookup APIs return only template agents."""
    engine = get_or_create_engine(db_uri)
    with engine.begin() as conn:
        # kind moved to omnigent_conversation_metadata; conversations no longer has it.
        conn.execute(
            sa.text(
                "INSERT INTO conversations "
                "(id, created_at, updated_at, root_conversation_id) "
                "VALUES (:id, :ts, :ts, :id)",
            ),
            # Raw SQL bypasses the Uuid16 TypeDecorator, so bind 16 raw bytes;
            # a 32-char hex string overflows the BINARY(16) column on MySQL.
            {"id": bytes.fromhex("3e2c8fc48e056223d18a47a8d4660491"), "ts": 1700000000},
        )
        conn.execute(
            sa.text(
                "INSERT INTO agents "
                "(id, created_at, name, bundle_location, version, kind) "
                "VALUES (:id, :ts, :name, :loc, 1, 2)",  # kind=2 → 'session'
            ),
            {
                "id": bytes.fromhex("6ec5d35246127ba7b23bd47aa95208ec"),
                "ts": 1700000001,
                "name": "session-only-agent",
                "loc": "ag_agent_store_session/bundle",
            },
        )
    template_agent = agent_store.create(
        agent_id="ee6a8659002db5242a56278b73f7a06d",
        name="template-agent",
        bundle_location="ag_agent_store_template/bundle",
    )

    assert agent_store.get_by_name("session-only-agent") is None
    page = agent_store.list(limit=100, order="asc")
    listed_names = [agent.name for agent in page.data]
    assert "session-only-agent" not in listed_names
    assert template_agent.name in listed_names


def test_create_with_description(agent_store: SqlAlchemyAgentStore) -> None:
    agent = agent_store.create(
        agent_id="81b344a1abb05d6096989e2aff583e37",
        name="helper",
        bundle_location="ag_test_helper/fakehash",
        description="A helper agent",
    )
    assert agent.description == "A helper agent"


def test_delete(agent_store: SqlAlchemyAgentStore) -> None:
    agent = agent_store.create(
        agent_id="ef3b53ae229c2fa6af1e4189fa27b74e",
        name="temp",
        bundle_location="ag_test_temp/fakehash",
    )
    assert agent_store.delete(agent.id) is True
    assert agent_store.get(agent.id) is None
    assert agent_store.delete(agent.id) is False


def test_list_pagination(agent_store: SqlAlchemyAgentStore) -> None:
    for i in range(5):
        agent_store.create(
            agent_id=f"{i:032x}", name=f"agent-{i}", bundle_location=f"{i:032x}/fakehash"
        )

    page1 = agent_store.list(limit=2)
    assert len(page1.data) == 2
    assert page1.has_more is True

    page2 = agent_store.list(limit=2, after=page1.last_id)
    assert len(page2.data) == 2
    assert page2.has_more is True

    page3 = agent_store.list(limit=2, after=page2.last_id)
    assert len(page3.data) == 1
    assert page3.has_more is False


def test_list_returns_newest_first(agent_store: SqlAlchemyAgentStore) -> None:
    a1 = agent_store.create(
        agent_id="7dc777d26c3e1b66897f9fa0bf4848fb",
        name="first",
        bundle_location="ag_test_first/fakehash",
    )
    a2 = agent_store.create(
        agent_id="c7ba0ac9893ab0ecef5f36f17b808045",
        name="second",
        bundle_location="ag_test_second/fakehash",
    )
    page = agent_store.list()
    ids = {a.id for a in page.data}
    # Both returned; ordering is (created_at DESC, id DESC) —
    # same-second items are ordered by ID, not insertion order.
    assert ids == {a1.id, a2.id}


def test_list_order_asc(agent_store: SqlAlchemyAgentStore) -> None:
    for i in range(3):
        agent_store.create(
            agent_id=f"{i:032x}", name=f"agent-{i}", bundle_location=f"{i:032x}/fakehash"
        )
    page_desc = agent_store.list(order="desc")
    page_asc = agent_store.list(order="asc")
    assert [a.id for a in page_asc.data] == list(reversed([a.id for a in page_desc.data]))


def test_list_before_cursor(agent_store: SqlAlchemyAgentStore) -> None:
    for i in range(5):
        agent_store.create(
            agent_id=f"{i:032x}", name=f"agent-{i}", bundle_location=f"{i:032x}/fakehash"
        )
    # Paginate with after, then use before on the last page's first item
    # to go backwards and verify no overlap.
    page1 = agent_store.list(limit=3)
    page2 = agent_store.list(limit=3, after=page1.last_id)
    # before the first item of page2 should give us page1's items
    back = agent_store.list(limit=3, before=page2.first_id)
    assert [a.id for a in back.data] == [a.id for a in page1.data]


def test_list_asc_with_after_cursor(agent_store: SqlAlchemyAgentStore) -> None:
    for i in range(5):
        agent_store.create(
            agent_id=f"{i:032x}", name=f"agent-{i}", bundle_location=f"{i:032x}/fakehash"
        )
    page1 = agent_store.list(limit=2, order="asc")
    assert len(page1.data) == 2
    assert page1.has_more is True

    page2 = agent_store.list(limit=2, order="asc", after=page1.last_id)
    assert len(page2.data) == 2
    assert page2.has_more is True

    page3 = agent_store.list(limit=2, order="asc", after=page2.last_id)
    assert len(page3.data) == 1
    assert page3.has_more is False

    # All pages together should equal the full asc listing
    all_ids = [a.id for a in page1.data + page2.data + page3.data]
    full_asc = agent_store.list(limit=100, order="asc")
    assert all_ids == [a.id for a in full_asc.data]


# ── Update tests ───────────────────────────────────────────────


def test_update_agent(agent_store: SqlAlchemyAgentStore) -> None:
    """update() changes bundle_location, bumps version, sets updated_at."""
    agent = agent_store.create(
        agent_id="409a6849f6efefc6ba8da809a29b9b0b",
        name="updatable",
        bundle_location="ag_test_upd/hash1",
    )
    # version=1 and updated_at=None on creation
    assert agent.version == 1
    assert agent.updated_at is None

    updated = agent_store.update("409a6849f6efefc6ba8da809a29b9b0b", "ag_test_upd/hash2")
    assert updated is not None
    assert updated.version == 2
    assert updated.bundle_location == "ag_test_upd/hash2"
    assert updated.updated_at is not None
    # Name stays the same
    assert updated.name == "updatable"


def test_update_nonexistent_agent(agent_store: SqlAlchemyAgentStore) -> None:
    """update() returns None for a nonexistent agent."""
    assert agent_store.update("5ff5b2e31fe10beb80134394037b17b0", "loc") is None


def test_update_increments_version(agent_store: SqlAlchemyAgentStore) -> None:
    """Multiple updates increment version monotonically."""
    agent_store.create(
        agent_id="9dafdd1d4311d9f16337323a6d653308",
        name="versioned",
        bundle_location="ag_test_ver/h1",
    )
    v2 = agent_store.update("9dafdd1d4311d9f16337323a6d653308", "ag_test_ver/h2")
    v3 = agent_store.update("9dafdd1d4311d9f16337323a6d653308", "ag_test_ver/h3")
    assert v2 is not None and v2.version == 2
    assert v3 is not None and v3.version == 3


def test_legacy_update_atomically_increments_after_a_concurrent_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_store = SqlAlchemyAgentStore(f"sqlite:///{tmp_path / 'legacy-cas.db'}")
    agent_id = "27a22eff35ea46a2b1b21a99d22ddcaa"
    agent_store.create(
        agent_id=agent_id,
        name="legacy-cas-race",
        bundle_location="ag_legacy_cas/v1",
    )
    legacy_read = Event()
    release_legacy = Event()
    pause_next_legacy_operation = True
    original_session = agent_store._session

    @contextmanager
    def interleaved_session():  # type: ignore[no-untyped-def]
        nonlocal pause_next_legacy_operation
        with original_session() as session:
            original_get = session.get
            original_execute = session.execute

            def pause_legacy() -> None:
                nonlocal pause_next_legacy_operation
                if pause_next_legacy_operation:
                    pause_next_legacy_operation = False
                    legacy_read.set()
                    assert release_legacy.wait(timeout=5)

            def paused_get(*args: object, **kwargs: object) -> object:
                row = original_get(*args, **kwargs)
                pause_legacy()
                return row

            def paused_execute(*args: object, **kwargs: object) -> object:
                if args and isinstance(args[0], sa.sql.dml.Update):
                    pause_legacy()
                return original_execute(*args, **kwargs)

            monkeypatch.setattr(session, "get", paused_get)
            monkeypatch.setattr(session, "execute", paused_execute)
            yield session

    monkeypatch.setattr(agent_store, "_session", interleaved_session)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            legacy_future = executor.submit(
                agent_store.update,
                agent_id,
                "ag_legacy_cas/legacy",
            )
            assert legacy_read.wait(timeout=5)
            try:
                cas = agent_store.update_template(
                    agent_id,
                    bundle_location="ag_legacy_cas/cas",
                    name="legacy-cas-race",
                    description=None,
                    expected_version=1,
                )
            finally:
                release_legacy.set()
            legacy = legacy_future.result(timeout=5)

        current = agent_store.get(agent_id)
        assert cas is not None and cas.version == 2
        assert legacy is not None and legacy.version == 3
        assert current is not None
        assert (current.bundle_location, current.version) == ("ag_legacy_cas/legacy", 3)
    finally:
        agent_store._engine.dispose()


def test_create_agent_has_version_1(agent_store: SqlAlchemyAgentStore) -> None:
    """Newly created agents start at version 1."""
    agent = agent_store.create(
        agent_id="3b1917f10e098e91d3e2fe6bd30104ef",
        name="fresh",
        bundle_location="ag_test_v1/hash",
    )
    assert agent.version == 1
    assert agent.updated_at is None


# ── Template optimistic update tests ─────────────────────────────────────


def test_update_template_checks_version_and_updates_metadata(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    agent_store.create(
        agent_id="c7c71b97a1df4a059fb0eaebd36b2a98",
        name="old-name",
        bundle_location="ag_template/old-hash",
        description="old description",
    )

    updated = agent_store.update_template(
        "c7c71b97a1df4a059fb0eaebd36b2a98",
        bundle_location="ag_template/new-hash",
        name="new-name",
        description="new description",
        expected_version=1,
    )

    assert updated is not None
    assert updated.name == "new-name"
    assert updated.description == "new description"
    assert updated.bundle_location == "ag_template/new-hash"
    assert updated.version == 2
    assert updated.updated_at is not None


def test_update_template_can_clear_or_retain_description(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    agent_store.create(
        agent_id="02906de20caa4f8ab001f29147114e4f",
        name="described",
        bundle_location="ag_description/v1",
        description="keep me",
    )

    retained = agent_store.update_template(
        "02906de20caa4f8ab001f29147114e4f",
        bundle_location="ag_description/v2",
        name="described",
        description="keep me",
        expected_version=1,
    )
    cleared = agent_store.update_template(
        "02906de20caa4f8ab001f29147114e4f",
        bundle_location="ag_description/v3",
        name="described",
        description=None,
        expected_version=2,
    )

    assert retained is not None and retained.description == "keep me"
    assert cleared is not None and cleared.description is None


def test_update_template_returns_none_for_missing_agent(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    assert (
        agent_store.update_template(
            "5ff5b2e31fe10beb80134394037b17b0",
            bundle_location="missing/v2",
            name="missing",
            description=None,
            expected_version=1,
        )
        is None
    )


def test_update_template_rejects_session_scoped_agent(
    agent_store: SqlAlchemyAgentStore,
    db_uri: str,
) -> None:
    agent_id = "673f55f2bf144765ab31cecf16346ec1"
    engine = get_or_create_engine(db_uri)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO agents "
                "(id, created_at, name, bundle_location, version, kind) "
                "VALUES (:id, :ts, :name, :loc, 1, 2)"
            ),
            {
                "id": bytes.fromhex(agent_id),
                "ts": 1700000000,
                "name": "session-copy",
                "loc": "ag_session/v1",
            },
        )

    with pytest.raises(ValueError, match="template"):
        agent_store.update_template(
            agent_id,
            bundle_location="ag_session/v2",
            name="renamed-session",
            description="must not change",
            expected_version=1,
        )

    unchanged = agent_store.get(agent_id)
    assert unchanged is not None
    assert (unchanged.name, unchanged.bundle_location, unchanged.version) == (
        "session-copy",
        "ag_session/v1",
        1,
    )


def test_update_template_reports_stale_actual_version_without_partial_update(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    agent_id = "25449e0ba5c54dd4a429443d32c842cb"
    agent_store.create(
        agent_id=agent_id,
        name="current",
        bundle_location="ag_conflict/v1",
        description="current description",
    )
    successful = agent_store.update_template(
        agent_id,
        bundle_location="ag_conflict/v2",
        name="current-v2",
        description="version two",
        expected_version=1,
    )
    assert successful is not None

    with pytest.raises(AgentVersionConflict) as raised:
        agent_store.update_template(
            agent_id,
            bundle_location="ag_conflict/stale",
            name="stale-name",
            description="stale description",
            expected_version=1,
        )

    assert raised.value.agent_id == agent_id
    assert raised.value.expected == 1
    assert raised.value.actual == 2
    unchanged = agent_store.get(agent_id)
    assert unchanged is not None
    assert (unchanged.name, unchanged.description, unchanged.bundle_location) == (
        "current-v2",
        "version two",
        "ag_conflict/v2",
    )


def test_update_template_rejects_duplicate_name_atomically(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    source_id = "98a08d2d4b414cc89436148595338775"
    agent_store.create(source_id, "source", "ag_source/v1", "source description")
    agent_store.create(
        "37a69b9466624281a854124c89f7ba86",
        "occupied",
        "ag_occupied/v1",
    )

    with pytest.raises(IntegrityError):
        agent_store.update_template(
            source_id,
            bundle_location="ag_source/v2",
            name="occupied",
            description="changed description",
            expected_version=1,
        )

    unchanged = agent_store.get(source_id)
    assert unchanged is not None
    assert (
        unchanged.name,
        unchanged.description,
        unchanged.bundle_location,
        unchanged.version,
        unchanged.updated_at,
    ) == ("source", "source description", "ag_source/v1", 1, None)


def test_update_template_name_uniqueness_is_workspace_scoped(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    agent_id = "d91130c6112449ec899f8fb759bcd901"
    with workspace_scope(1):
        agent_store.create(agent_id, "workspace-one", "ag_ws1/v1")
    with workspace_scope(2):
        agent_store.create(agent_id, "shared-name", "ag_ws2/v1")

    with workspace_scope(1):
        updated = agent_store.update_template(
            agent_id,
            bundle_location="ag_ws1/v2",
            name="shared-name",
            description=None,
            expected_version=1,
        )
        assert updated is not None
        assert (updated.name, updated.bundle_location, updated.version) == (
            "shared-name",
            "ag_ws1/v2",
            2,
        )
    with workspace_scope(2):
        untouched = agent_store.get(agent_id)
        assert untouched is not None
        assert (untouched.bundle_location, untouched.version) == ("ag_ws2/v1", 1)


def test_update_template_same_expected_version_has_single_winner(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    agent_id = "5ae3037894a648f0a18b86910846cdca"
    agent_store.create(agent_id, "concurrent", "ag_concurrent/v1")
    barrier = Barrier(2)

    def update(suffix: str) -> int:
        barrier.wait()
        result = agent_store.update_template(
            agent_id,
            bundle_location=f"ag_concurrent/{suffix}",
            name=f"concurrent-{suffix}",
            description=suffix,
            expected_version=1,
        )
        assert result is not None
        return result.version

    outcomes: list[int | AgentVersionConflict] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(update, suffix) for suffix in ("left", "right")]
        for future in futures:
            try:
                outcomes.append(future.result())
            except AgentVersionConflict as exc:
                outcomes.append(exc)

    successes = [result for result in outcomes if isinstance(result, int)]
    conflicts = [result for result in outcomes if isinstance(result, AgentVersionConflict)]
    assert successes == [2]
    assert len(conflicts) == 1
    assert conflicts[0].expected == 1
    assert conflicts[0].actual == 2


def test_concurrent_template_renames_to_same_name_have_single_winner(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    left_id = "a22e50f5855047f6b70498893b80950e"
    right_id = "c8e819314267470bbf82389b49a832d0"
    agent_store.create(left_id, "rename-left", "ag_rename_left/v1")
    agent_store.create(right_id, "rename-right", "ag_rename_right/v1")
    barrier = Barrier(2)

    def rename(agent_id: str) -> None:
        barrier.wait()
        agent_store.update_template(
            agent_id,
            bundle_location=f"{agent_id}/v2",
            name="shared-rename-target",
            description=None,
            expected_version=1,
        )

    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(rename, agent_id) for agent_id in (left_id, right_id)]
        for future in futures:
            try:
                future.result()
            except BaseException as exc:
                errors.append(exc)

    assert len(errors) == 1
    assert isinstance(errors[0], IntegrityError)
    assert (
        len([a for a in agent_store.list(limit=100).data if a.name == "shared-rename-target"]) == 1
    )


def test_concurrent_creates_in_empty_workspace_have_single_winner(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    barrier = Barrier(2)

    def create(agent_id: str) -> None:
        barrier.wait()
        agent_store.create(agent_id, "shared-create-target", f"{agent_id}/v1")

    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(create, agent_id)
            for agent_id in (
                "8747116159034a66846247026626527f",
                "ac59414ec1b94d1696da8cc31790723b",
            )
        ]
        for future in futures:
            try:
                future.result()
            except BaseException as exc:
                errors.append(exc)

    assert len(errors) == 1
    assert isinstance(errors[0], IntegrityError)
    assert (
        len([a for a in agent_store.list(limit=100).data if a.name == "shared-create-target"]) == 1
    )


def test_concurrent_create_and_update_to_same_name_have_single_winner(
    agent_store: SqlAlchemyAgentStore,
) -> None:
    source_id = "3f16d77996ae40d18b9726a4458821b2"
    agent_store.create(source_id, "create-update-source", "ag_create_update/v1")
    barrier = Barrier(2)

    def create() -> None:
        barrier.wait()
        agent_store.create(
            "5cbe3a06dd804a259b269d7d2de74c97",
            "shared-create-update-target",
            "ag_created/v1",
        )

    def update() -> None:
        barrier.wait()
        agent_store.update_template(
            source_id,
            bundle_location="ag_create_update/v2",
            name="shared-create-update-target",
            description=None,
            expected_version=1,
        )

    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create), executor.submit(update)]
        for future in futures:
            try:
                future.result()
            except BaseException as exc:
                errors.append(exc)

    assert len(errors) == 1
    assert isinstance(errors[0], IntegrityError)
    assert (
        len(
            [
                a
                for a in agent_store.list(limit=100).data
                if a.name == "shared-create-update-target"
            ]
        )
        == 1
    )


def test_template_name_lock_protocol_is_shared_by_create_and_update(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    original = agent_store._template_write_session

    def recording_session(workspace_id: int):  # type: ignore[no-untyped-def]
        calls.append(workspace_id)
        return original(workspace_id)

    monkeypatch.setattr(agent_store, "_template_write_session", recording_session)
    agent_id = "0a5452298892469799899205761c08be"
    agent_store.create(agent_id, "locked-create", "ag_locked/v1")
    agent_store.update_template(
        agent_id,
        bundle_location="ag_locked/v2",
        name="locked-update",
        description=None,
        expected_version=1,
    )

    assert calls == [0, 0]


def test_session_scoped_name_does_not_conflict_with_template_name_lock(
    agent_store: SqlAlchemyAgentStore,
    db_uri: str,
) -> None:
    engine = get_or_create_engine(db_uri)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO agents "
                "(id, created_at, name, bundle_location, version, kind) "
                "VALUES (:id, :ts, :name, :loc, 1, 2)"
            ),
            {
                "id": bytes.fromhex("6466337c0a3645a1a9e7990175296444"),
                "ts": 1700000000,
                "name": "session-shared-name",
                "loc": "ag_session_shared/v1",
            },
        )

    created = agent_store.create(
        "0915be1d0c7f4e148aa422507eefce05",
        "session-shared-name",
        "ag_template_shared/v1",
    )
    assert created.name == "session-shared-name"


def test_template_name_lock_keys_are_stable_bounded_and_opaque() -> None:
    postgres_key = SqlAlchemyAgentStore._template_write_lock_id(7)
    mysql_key = SqlAlchemyAgentStore._template_write_lock_name(7)

    assert postgres_key == SqlAlchemyAgentStore._template_write_lock_id(7)
    assert -(2**63) <= postgres_key < 2**63
    assert postgres_key != SqlAlchemyAgentStore._template_write_lock_id(8)
    assert len(mysql_key.encode()) <= 64
    assert "private-agent-name" not in mysql_key


@pytest.mark.parametrize("scenario", ["create-create", "rename-rename", "create-update"])
def test_mysql_collation_equivalent_names_share_workspace_lock(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    calls: list[int] = []
    original = agent_store._template_write_session

    def recording_session(workspace_id: int):  # type: ignore[no-untyped-def]
        calls.append(workspace_id)
        return original(workspace_id)

    monkeypatch.setattr(agent_store, "_template_write_session", recording_session)
    left_id = "c19494f1f64f4a70a1032d6edd12a5cc"
    right_id = "a3d42ca19053408d8f7d2253e2190716"

    if scenario == "create-create":
        agent_store.create(left_id, "Foo", "ag_case_left/v1")
        agent_store.create(right_id, "foo", "ag_case_right/v1")
    else:
        agent_store.create(left_id, "case-left", "ag_case_left/v1")
        agent_store.create(right_id, "case-right", "ag_case_right/v1")
        calls.clear()
        if scenario == "rename-rename":
            agent_store.update_template(left_id, "ag_case_left/v2", "Foo", None, 1)
            agent_store.update_template(right_id, "ag_case_right/v2", "foo", None, 1)
        else:
            agent_store.create(
                "925e6b61e7df4fbcaf66c1cd38f6034d",
                "Foo",
                "ag_case_created/v1",
            )
            agent_store.update_template(left_id, "ag_case_left/v2", "foo", None, 1)

    assert calls == [0, 0]


def test_template_write_lock_dialect_protocols(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []

    class Dialect:
        name = "postgresql"

    class Engine:
        dialect = Dialect()

    class Session:
        def execute(self, statement: object, params: object) -> None:
            events.append((str(statement), params))

    @contextmanager
    def session_maker():  # type: ignore[no-untyped-def]
        yield Session()

    monkeypatch.setattr(agent_store, "_engine", Engine())
    monkeypatch.setattr(agent_store, "_session", session_maker)
    with agent_store._template_write_session(9):
        events.append(("body", 9))

    assert "pg_advisory_xact_lock" in events[0][0]
    assert events[0][1] == {"lock_id": agent_store._template_write_lock_id(9)}
    assert events[1] == ("body", 9)

    Engine.dialect.name = "unknown"
    with pytest.raises(RuntimeError, match="unsupported"):
        with agent_store._template_write_session(9):
            pytest.fail("unknown dialect must fail before yielding")

    Engine.dialect.name = "sqlite"

    @contextmanager
    def immediate_session():  # type: ignore[no-untyped-def]
        events.append(("sqlite-immediate", 9))
        yield Session()

    monkeypatch.setattr(agent_store, "_template_update_session", immediate_session)
    with agent_store._template_write_session(9):
        pass
    assert events[-1] == ("sqlite-immediate", 9)


@pytest.mark.parametrize(
    ("failure", "release_failure"),
    [
        (None, None),
        ("body", None),
        ("begin", None),
        ("commit", None),
        (None, "execute"),
        (None, "scalar"),
        (None, "zero"),
        (None, "null"),
        ("body", "execute"),
        ("commit", "zero"),
    ],
)
def test_mysql_template_name_lock_releases_after_transaction(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    release_failure: str | None,
) -> None:
    events: list[str] = []

    class Result:
        def __init__(self, release: bool = False) -> None:
            self.release = release

        def scalar_one(self) -> int | None:
            if self.release and release_failure == "scalar":
                raise RuntimeError("release scalar failed")
            if self.release and release_failure == "zero":
                return 0
            if self.release and release_failure == "null":
                return None
            return 1

    class Transaction:
        is_active = True

        def commit(self) -> None:
            events.append("transaction.commit")
            if failure == "commit":
                raise RuntimeError("commit failed")
            self.is_active = False

        def rollback(self) -> None:
            events.append("transaction.rollback")
            self.is_active = False

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object = None) -> Result:
            del params
            sql = str(statement)
            release = "RELEASE_LOCK" in sql
            events.append("release" if release else "acquire")
            if release and release_failure == "execute":
                raise RuntimeError("release execute failed")
            return Result(release)

        def commit(self) -> None:
            events.append("connection.commit")

        def rollback(self) -> None:
            events.append("connection.rollback")

        def in_transaction(self) -> bool:
            return False

        def invalidate(self) -> None:
            events.append("invalidate")

        def begin(self) -> Transaction:
            events.append("transaction.begin")
            if failure == "begin":
                raise RuntimeError("begin failed")
            return Transaction()

    class Engine:
        class Dialect:
            name = "mysql"

        dialect = Dialect()

        def connect(self) -> Connection:
            return Connection()

    class Session:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def __enter__(self) -> Session:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def flush(self) -> None:
            events.append("session.flush")

    monkeypatch.setattr(agent_store, "_engine", Engine())
    monkeypatch.setattr(agent_store_sqlalchemy, "Session", Session)

    expect_error = failure is not None or release_failure is not None
    expectation = pytest.raises(RuntimeError) if expect_error else nullcontext()
    with expectation as raised:
        with agent_store._template_write_session(7):
            events.append("body")
            if failure == "body":
                raise RuntimeError("body failed")

    assert "release" in events
    assert ("invalidate" in events) is (release_failure is not None)
    if failure != "begin":
        terminal = "transaction.rollback" if failure else "transaction.commit"
        assert events.index(terminal) < events.index("release")
    if failure is not None:
        expected = f"{failure} failed"
        assert raised is not None
        assert expected in str(raised.value)
        if release_failure is not None:
            assert any("lock cleanup failed" in note for note in raised.value.__notes__)


# ── get_names tests ───────────────────────────────────────────────


def test_template_lock_connection_honors_truthy_exit_suppression(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_error = RuntimeError("body failed")
    exit_arguments: list[tuple[object, object, object]] = []
    connection = object()

    class ConnectionContext:
        def __enter__(self) -> object:
            return connection

        def __exit__(self, *args: object) -> bool:
            exit_arguments.append(args)
            return True

    class Engine:
        def connect(self) -> ConnectionContext:
            return ConnectionContext()

    monkeypatch.setattr(agent_store, "_engine", Engine())

    with agent_store._template_lock_connection() as entered:
        assert entered is connection
        raise body_error

    assert len(exit_arguments) == 1
    error_type, error, traceback = exit_arguments[0]
    assert error_type is RuntimeError
    assert error is body_error
    assert traceback is body_error.__traceback__


def test_template_lock_cleanup_observers_do_not_restore_stale_dialect_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_entered = Event()
    release_first = Event()
    second_waiting_for_lock = Event()

    class OverlapLock:
        def __init__(self) -> None:
            self.lock = RLock()
            self.enter_count = 0

        def __enter__(self) -> OverlapLock:
            self.enter_count += 1
            if self.enter_count == 2:
                second_waiting_for_lock.set()
            self.lock.acquire()
            return self

        def __exit__(self, *args: object) -> None:
            del args
            self.lock.release()

    class Dialect:
        def do_rollback(self, candidate: object) -> None:
            del candidate

        def do_terminate(self, candidate: object) -> None:
            del candidate

    class Connection:
        dialect = Dialect()

    dialect = Connection.dialect
    monkeypatch.setattr(SqlAlchemyAgentStore, "_template_termination_lock", OverlapLock())

    def observe_first() -> None:
        with SqlAlchemyAgentStore._observe_template_lock_driver_cleanup(
            Connection(),
            object(),
            [],
            [],
        ):
            first_entered.set()
            assert release_first.wait(timeout=1)

    def observe_second() -> None:
        assert first_entered.wait(timeout=1)
        with SqlAlchemyAgentStore._observe_template_lock_driver_cleanup(
            Connection(),
            object(),
            [],
            [],
        ):
            pass

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(observe_first)
        second = executor.submit(observe_second)
        assert second_waiting_for_lock.wait(timeout=1)
        release_first.set()
        first.result(timeout=1)
        second.result(timeout=1)

    assert "do_rollback" not in dialect.__dict__
    assert "do_terminate" not in dialect.__dict__


def test_nested_template_cleanup_observers_for_same_driver_unregister_by_identity() -> None:
    driver = object()
    rollback_failure = RuntimeError("outer rollback failed")
    termination_failure = RuntimeError("outer termination failed")
    termination_attempts = 0

    class Dialect:
        def do_rollback(self, candidate: object) -> None:
            assert candidate is driver
            raise rollback_failure

        def do_terminate(self, candidate: object) -> None:
            nonlocal termination_attempts
            assert candidate is driver
            termination_attempts += 1
            if termination_attempts <= 2:
                raise termination_failure

    class Connection:
        dialect = Dialect()

    dialect = Connection.dialect
    outer_reset_failures: list[BaseException] = []
    outer_termination_failures: list[BaseException] = []
    inner_reset_failures: list[BaseException] = []
    inner_termination_failures: list[BaseException] = []
    assert not SqlAlchemyAgentStore._template_cleanup_dispatchers

    with SqlAlchemyAgentStore._observe_template_lock_driver_cleanup(
        Connection(),
        driver,
        outer_reset_failures,
        outer_termination_failures,
    ):
        with SqlAlchemyAgentStore._observe_template_lock_driver_cleanup(
            Connection(),
            driver,
            inner_reset_failures,
            inner_termination_failures,
        ):
            pass

        with pytest.raises(RuntimeError, match="outer rollback failed"):
            dialect.do_rollback(driver)
        with pytest.raises(RuntimeError, match="outer termination failed"):
            dialect.do_terminate(driver)

    assert outer_reset_failures == [rollback_failure]
    assert outer_termination_failures == [termination_failure, termination_failure]
    assert inner_reset_failures == []
    assert inner_termination_failures == []
    assert termination_attempts == 3
    assert not SqlAlchemyAgentStore._template_cleanup_dispatchers
    assert "do_rollback" not in dialect.__dict__
    assert "do_terminate" not in dialect.__dict__


def test_template_lock_connections_for_different_workspaces_do_not_serialize(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_entered = Event()
    second_entered = Event()
    release_first = Event()
    lock_names: list[str] = []

    class Dialect:
        name = "mysql"

        def do_rollback(self, candidate: object) -> None:
            del candidate

        def do_terminate(self, candidate: object) -> None:
            del candidate

    class DriverHolder:
        def __init__(self, driver: object) -> None:
            self.driver_connection = driver

    class Result:
        def scalar_one(self) -> int:
            return 1

    class Transaction:
        is_active = True

        def commit(self) -> None:
            self.is_active = False

        def rollback(self) -> None:
            self.is_active = False

    class Connection:
        def __init__(self, dialect: Dialect) -> None:
            self.dialect = dialect
            self.connection = DriverHolder(object())

        def execute(self, statement: object, params: dict[str, object]) -> Result:
            if "GET_LOCK" in str(statement):
                lock_names.append(str(params["lock_name"]))
            return Result()

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def begin(self) -> Transaction:
            return Transaction()

        def in_transaction(self) -> bool:
            return False

    class ConnectionContext:
        def __init__(self, dialect: Dialect) -> None:
            self.connection = Connection(dialect)

        def __enter__(self) -> Connection:
            return self.connection

        def __exit__(self, *args: object) -> None:
            del args

    class Engine:
        def __init__(self) -> None:
            self.dialect = Dialect()

        def connect(self) -> ConnectionContext:
            return ConnectionContext(self.dialect)

    class Session:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def __enter__(self) -> Session:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def flush(self) -> None:
            return None

    first_store = agent_store
    second_store = object.__new__(SqlAlchemyAgentStore)
    first_store._engine = Engine()  # type: ignore[assignment]
    second_store._engine = Engine()  # type: ignore[assignment]
    monkeypatch.setattr(agent_store_sqlalchemy, "Session", Session)

    def write(
        store: SqlAlchemyAgentStore,
        workspace_id: int,
        entered: Event,
        release: Event | None,
    ) -> None:
        with store._template_write_session(workspace_id):
            entered.set()
            if release is not None:
                assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(write, first_store, 11, first_entered, release_first)
        assert first_entered.wait(timeout=1)
        second = executor.submit(write, second_store, 22, second_entered, None)
        try:
            assert second_entered.wait(timeout=1)
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    assert len(lock_names) == 2
    assert lock_names[0] != lock_names[1]
    assert not SqlAlchemyAgentStore._template_cleanup_dispatchers


@pytest.mark.parametrize("failure", ["execute", "commit"])
def test_mysql_template_lock_retries_termination_after_auto_disconnect(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    drivers: list[TrackingDriver] = []

    class TrackingDriver(sqlite3.Connection):
        named_lock = False
        fail_next_commit = False
        close_attempts = 0

        def commit(self) -> None:
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise sqlite3.OperationalError("driver disconnected during commit")
            super().commit()

        def close(self) -> None:
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise sqlite3.OperationalError("driver close failed")
            self.named_lock = False
            super().close()

    def create_driver() -> TrackingDriver:
        driver = sqlite3.connect(":memory:", factory=TrackingDriver)
        driver.create_function(
            "GET_LOCK",
            2,
            lambda _name, _timeout: setattr(driver, "named_lock", True) or 1,
        )
        driver.create_function(
            "RELEASE_LOCK",
            1,
            lambda _name: setattr(driver, "named_lock", False) or 1,
        )

        def disconnect() -> None:
            raise sqlite3.OperationalError("driver disconnected during execute")

        driver.create_function("disconnect", 0, disconnect)
        drivers.append(driver)
        return driver

    engine = sa.create_engine(
        "sqlite://",
        creator=create_driver,
        poolclass=sa.pool.QueuePool,
        pool_size=1,
        max_overflow=0,
    )
    engine.dialect.name = "mysql"
    monkeypatch.setattr(
        engine.dialect,
        "is_disconnect",
        lambda error, _connection, _cursor: isinstance(error, sqlite3.OperationalError),
    )
    monkeypatch.setattr(agent_store, "_engine", engine)

    try:
        with pytest.raises(sa.exc.DBAPIError) as raised:
            with agent_store._template_write_session(7) as session:
                driver = drivers[0]
                assert driver.named_lock
                if failure == "execute":
                    session.execute(sa.text("SELECT disconnect()"))
                else:
                    driver.fail_next_commit = True

        driver = drivers[0]
        assert raised.value.connection_invalidated
        assert driver.close_attempts == 2
        assert not driver.named_lock
        assert any(
            "Template lock driver termination failed" in note and "driver close failed" in note
            for note in raised.value.__notes__
        )
    finally:
        engine.dispose()
        for driver in drivers:
            sqlite3.Connection.close(driver)


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "release",
        "body",
        "commit",
        "acquire-execute",
        "acquire-scalar",
        "detach-failure",
        "driver-close-failure",
        "terminate-success",
        "terminate-close",
        "checkin-body",
        "checkin-commit",
        "checkin-success",
        "release-checkin",
        "reset-success",
        "reset-body",
        "reset-commit",
    ],
)
def test_mysql_template_lock_hard_discards_after_invalidation_failure(
    agent_store: SqlAlchemyAgentStore,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    events: list[str] = []
    drivers: list[TrackingDriver] = []
    delegated_drivers: list[sqlite3.Connection] = []

    class TrackingDriver(sqlite3.Connection):
        named_lock = False
        fail_next_close = False
        fail_next_rollback = False
        delegated_rollback: sqlite3.Connection | None = None
        delegated_terminate: sqlite3.Connection | None = None

        def rollback(self) -> None:
            if self.delegated_rollback is not None:
                delegated = self.delegated_rollback
                self.delegated_rollback = None
                events.append("other-driver.rollback")
                engine.dialect.do_rollback(delegated)
            if self.fail_next_rollback:
                self.fail_next_rollback = False
                events.append("driver.reset-failure")
                raise RuntimeError("driver reset failed")
            super().rollback()

        def close(self) -> None:
            if self.delegated_terminate is not None:
                delegated = self.delegated_terminate
                self.delegated_terminate = None
                events.append("other-driver.terminate")
                engine.dialect.do_terminate(delegated)
            events.append("driver.close")
            if self.fail_next_close:
                self.fail_next_close = False
                raise RuntimeError("driver close failed")
            self.named_lock = False
            super().close()

    def create_driver() -> TrackingDriver:
        driver = sqlite3.connect(":memory:", factory=TrackingDriver)
        drivers.append(driver)
        return driver

    engine = sa.create_engine(
        "sqlite://",
        creator=create_driver,
        poolclass=sa.pool.QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )

    def fail_invalidation(*args: object) -> None:
        del args
        events.append("invalidate-listener")
        if not scenario.startswith(("checkin-", "terminate-", "reset-")):
            raise RuntimeError("invalidate listener failed")

    def fail_detach(*args: object) -> None:
        del args
        events.append("detach-listener")
        if scenario == "detach-failure":
            raise RuntimeError("detach listener failed")

    sa.event.listen(engine.pool, "invalidate", fail_invalidation)
    sa.event.listen(engine.pool, "detach", fail_detach)

    def fail_checkin(driver: object, *args: object) -> None:
        del args
        if drivers and driver is drivers[0]:
            events.append("checkin-listener")
            if scenario in {
                "checkin-body",
                "checkin-commit",
                "checkin-success",
                "release-checkin",
            }:
                raise RuntimeError("checkin listener failed")

    sa.event.listen(engine.pool, "checkin", fail_checkin)

    class Result:
        def __init__(self, release: bool, driver: TrackingDriver) -> None:
            self.release = release
            self.driver = driver

        def scalar_one(self) -> int:
            if not self.release and scenario == "acquire-scalar":
                raise RuntimeError("acquire scalar failed")
            if self.release:
                self.driver.named_lock = False
            return 1

    class Transaction:
        is_active = True

        def commit(self) -> None:
            events.append("transaction.commit")
            if scenario in {"commit", "checkin-commit", "reset-commit"}:
                raise RuntimeError("commit failed")
            self.is_active = False

        def rollback(self) -> None:
            events.append("transaction.rollback")
            self.is_active = False

    class Connection:
        def __init__(self, inner: sa.Connection) -> None:
            self.inner = inner
            self.driver = inner.connection.driver_connection

        @property
        def connection(self) -> object:
            return self.inner.connection

        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            self.inner.__exit__(*args)

        @property
        def dialect(self) -> object:
            return self.inner.dialect

        def execute(self, statement: object, params: object = None) -> Result:
            del params
            release = "RELEASE_LOCK" in str(statement)
            events.append("release" if release else "acquire")
            if not release:
                self.driver.named_lock = True
                self.driver.fail_next_close = scenario in {
                    "driver-close-failure",
                    "terminate-close",
                } or scenario.startswith("reset-")
                self.driver.fail_next_rollback = scenario.startswith("reset-")
                if scenario == "reset-success":
                    rollback_driver = sqlite3.connect(":memory:")
                    terminate_driver = sqlite3.connect(":memory:")
                    delegated_drivers.extend((rollback_driver, terminate_driver))
                    self.driver.delegated_rollback = rollback_driver
                    self.driver.delegated_terminate = terminate_driver
                if scenario == "acquire-execute":
                    raise RuntimeError("acquire execute failed")
            elif scenario in {
                "release",
                "body",
                "commit",
                "detach-failure",
                "driver-close-failure",
                "terminate-success",
                "terminate-close",
                "release-checkin",
            }:
                raise RuntimeError("release execute failed")
            return Result(release, self.driver)

        def commit(self) -> None:
            events.append("connection.commit")

        def rollback(self) -> None:
            events.append("connection.rollback")

        def in_transaction(self) -> bool:
            return False

        def invalidate(self) -> None:
            events.append("invalidate")
            self.inner.invalidate()

        def detach(self) -> None:
            events.append("detach")
            self.inner.detach()

        def begin(self) -> Transaction:
            events.append("transaction.begin")
            return Transaction()

    class Engine:
        class Dialect:
            name = "mysql"

        dialect = Dialect()

        def connect(self) -> Connection:
            return Connection(engine.connect())

    class Session:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def __enter__(self) -> Session:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def flush(self) -> None:
            events.append("session.flush")

    monkeypatch.setattr(agent_store, "_engine", Engine())
    monkeypatch.setattr(agent_store_sqlalchemy, "Session", Session)

    try:
        expectation = nullcontext() if scenario == "success" else pytest.raises(RuntimeError)
        with expectation as raised:
            with agent_store._template_write_session(7):
                events.append("body")
                if scenario in {
                    "body",
                    "detach-failure",
                    "driver-close-failure",
                    "terminate-success",
                    "terminate-close",
                    "checkin-body",
                    "reset-body",
                }:
                    raise RuntimeError("body failed")

        failed_driver = drivers[0]
        assert engine.pool.checkedout() == 0
        with engine.connect() as replacement:
            replacement_driver = replacement.connection.driver_connection
        assert engine.pool.checkedout() == 0

        if scenario == "success":
            assert raised is None
            assert replacement_driver is failed_driver
            assert not failed_driver.named_lock
            assert "invalidate" not in events
            assert "detach" not in events
            assert "driver.close" not in events
            return

        assert raised is not None
        expected_primary = {
            "release": "Could not release the template name lock",
            "body": "body failed",
            "commit": "commit failed",
            "acquire-execute": "acquire execute failed",
            "acquire-scalar": "acquire scalar failed",
            "detach-failure": "body failed",
            "driver-close-failure": "body failed",
            "terminate-success": "body failed",
            "terminate-close": "body failed",
            "checkin-body": "body failed",
            "checkin-commit": "commit failed",
            "checkin-success": "Could not clean up the template lock connection",
            "release-checkin": "Could not release the template name lock",
            "reset-success": "Could not clean up the template lock connection",
            "reset-body": "body failed",
            "reset-commit": "commit failed",
        }[scenario]
        assert str(raised.value) == expected_primary
        notes = raised.value.__notes__
        if scenario.startswith("reset-"):
            assert any("driver reset failed" in note for note in notes)
            assert any("driver close failed" in note for note in notes)
        elif scenario.startswith("checkin-"):
            assert any("checkin listener failed" in note for note in notes)
        elif scenario == "terminate-close":
            assert any("driver close failed" in note for note in notes)
        elif scenario != "terminate-success":
            assert any("invalidate listener failed" in note for note in notes)
        if scenario not in {
            "acquire-execute",
            "acquire-scalar",
            "checkin-body",
            "checkin-commit",
            "checkin-success",
            "reset-success",
            "reset-body",
            "reset-commit",
        }:
            assert any("release execute failed" in note for note in notes)
        if scenario == "detach-failure":
            assert any("detach listener failed" in note for note in notes)
        if scenario == "driver-close-failure":
            assert any("driver close failed" in note for note in notes)

        if scenario.startswith("reset-"):
            assert events.index("release") < events.index("driver.reset-failure")
            assert events.index("driver.reset-failure") < events.index("driver.close")
            assert events.count("driver.close") == 2
        elif scenario.startswith("checkin-"):
            assert events.index("release") < events.index("checkin-listener")
        elif scenario.startswith("terminate-"):
            assert events.index("invalidate") < events.index("driver.close")
        else:
            assert events.index("invalidate") < events.index("detach")
            assert events.index("detach") < events.index("driver.close")
        if scenario == "release-checkin":
            assert "checkin-listener" not in events
            assert events.count("driver.close") == 1
        if scenario == "terminate-close":
            assert events.count("driver.close") == 2
        if scenario == "terminate-success":
            assert events.count("driver.close") == 1
        if scenario == "reset-success":
            assert events.count("other-driver.rollback") == 1
            assert events.count("other-driver.terminate") == 1
        assert replacement_driver is not failed_driver
        assert not failed_driver.named_lock
    finally:
        engine.dispose()
        for delegated_driver in delegated_drivers:
            delegated_driver.close()


def test_get_names_returns_id_to_name_mapping(agent_store: SqlAlchemyAgentStore) -> None:
    """get_names batch-fetches agent names by ID."""
    agent_store.create(
        agent_id="3f1269c64e8e0dae1e03bd1472ff4d84",
        name="alpha",
        bundle_location="ag_names_a/hash",
    )
    agent_store.create(
        agent_id="1dd1e3e87699fdd5c6d60680291dbaef", name="beta", bundle_location="ag_names_b/hash"
    )
    result = agent_store.get_names(
        ["3f1269c64e8e0dae1e03bd1472ff4d84", "1dd1e3e87699fdd5c6d60680291dbaef"]
    )
    assert result == {
        "3f1269c64e8e0dae1e03bd1472ff4d84": "alpha",
        "1dd1e3e87699fdd5c6d60680291dbaef": "beta",
    }


def test_get_names_omits_missing_ids(agent_store: SqlAlchemyAgentStore) -> None:
    """get_names silently omits IDs not found in the store."""
    agent_store.create(
        agent_id="e78cb9ee170f482daddce8809f06daec",
        name="gamma",
        bundle_location="ag_names_c/hash",
    )
    result = agent_store.get_names(
        ["e78cb9ee170f482daddce8809f06daec", "5ff5b2e31fe10beb80134394037b17b0"]
    )
    assert result == {"e78cb9ee170f482daddce8809f06daec": "gamma"}


def test_get_names_empty_input(agent_store: SqlAlchemyAgentStore) -> None:
    """get_names with empty list returns empty dict without hitting DB."""
    assert agent_store.get_names([]) == {}


# ── list edge cases ───────────────────────────────────────────────


def test_list_empty(agent_store: SqlAlchemyAgentStore) -> None:
    """list on an empty store returns empty PagedList."""
    page = agent_store.list()
    assert page.data == []
    assert page.first_id is None
    assert page.last_id is None
    assert page.has_more is False


def test_delete_nonexistent_returns_false(agent_store: SqlAlchemyAgentStore) -> None:
    """delete returns False for an ID that was never created."""
    result = agent_store.delete("5996d55aa263c10a717e2ee631f46409")
    assert result is False
