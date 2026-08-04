# Multi-Agent Feishu Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy Team/AgentProfile execution path with Agent Bundle-pinned root Sessions and an idempotent Run/Task/Attempt projection of the real Session tree, including Agent-scoped Feishu routing, durable multi-repository worktree leases, and a Session-backed Run Inspector.

**Architecture:** A Run creation service snapshots `agent_id + bundle_version + bundle_digest`, creates one root Coordinator Session pinned to that snapshot, and submits the initial input through the existing Session event API. Existing `sys_session_send`, child Session creation, runner lifecycle, Parent Inbox, and auto-wake remain the only execution engine; a projection service observes their durable events and updates Run/Task/Attempt read models without starting Workers or inventing dependencies. Feishu and WebUI call the same Run service, while legacy Team data remains read-only for compatibility diagnostics.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite/PostgreSQL-compatible migrations, pytest/pytest-asyncio, React 19, TypeScript, TanStack Query, Vitest, Testing Library.

---

## Scope and invariants

This plan implements these non-negotiable invariants:

1. A started Run and every Session in its tree use one immutable Agent Bundle snapshot.
2. `AgentCache` may hold multiple Digests for one Agent concurrently.
3. Run projection code never starts a Worker, wakes a Coordinator, chooses a Harness, or retries a task.
4. One logical Dispatch creates one Task and one Attempt; replaying its source event is a no-op.
5. Reusing the same `(agent, title)` Child Session for another turn creates a new Attempt, not a new Task.
6. Task dependencies exist only when an explicit plan/dispatch event supplies them.
7. Feishu chat/thread bindings point to `agent_id`, never Team ID or Worker Profile ID.
8. A running Run's `workspace_id`, Bundle version, and Bundle Digest never change.
9. Legacy Team rows are preserved and diagnosable but cannot create or modify executable configuration.
10. Inspector responses reference existing Session items and logs; they do not duplicate transcripts into Run tables.

## File map

### New backend files

- `omnigent/entities/run_projection.py` — immutable Bundle snapshot plus Run, Task, Attempt, event, and Inspector records.
- `omnigent/stores/run_store/__init__.py` — storage protocol and conflict/not-found errors.
- `omnigent/stores/run_store/sqlalchemy_store.py` — transactional Run projection persistence and Inspector queries.
- `omnigent/runs/__init__.py` — public runtime exports.
- `omnigent/runs/projection.py` — pure Session lifecycle to Run/Task/Attempt projection logic.
- `omnigent/runs/service.py` — unified Run creation service used by WebUI, Feishu, and future scheduled entry points.
- `omnigent/server/routes/runs.py` — authenticated Run creation/list/detail/event routes.
- `omnigent/integrations/lark/store.py` — durable Agent-scoped installation and chat/thread binding store.
- `omnigent/db/migrations/versions/zc1d2e3f4a5b_pin_bundle_and_project_sessions.py` — additive schema and compatibility backfill.
- `tests/runs/test_projection.py` — pure projection RED/GREEN tests.
- `tests/runs/test_service.py` — unified Run service tests.
- `tests/stores/test_run_store.py` — SQL store, idempotency, and Inspector query tests.
- `tests/server/test_runs_routes.py` — Run API contract tests.
- `tests/server/integration/test_run_projection.py` — real Conversation/Session persistence projection tests.
- `web/src/lib/runsApi.ts` — typed Run API client.
- `web/src/hooks/useAgentRuns.ts` — Agent-scoped list/detail queries.
- `web/src/components/runs/RunInspector.test.tsx` — Inspector contract and Session-link tests.

### Existing backend files to modify

- `omnigent/entities/agent.py` — `AgentBundleSnapshot` value and digest validation.
- `omnigent/entities/conversation.py` — pinned Bundle version, Digest, and location fields.
- `omnigent/runtime/agent_cache.py` — `(agent_id, digest, expand_env)` cache identity and multi-version eviction.
- `omnigent/db/db_models.py` — Conversation, Run, Task, Attempt, projection event, Feishu binding, and lease columns/models.
- `omnigent/db/converters.py` — SQL Conversation to entity Bundle snapshot conversion.
- `omnigent/stores/conversation_store/__init__.py` — create API Bundle snapshot parameters.
- `omnigent/stores/conversation_store/sqlalchemy_store.py` — persist/inherit pinned Bundle values atomically.
- `omnigent/runner/session_init_protocol.py` — send pinned Bundle values to the runner.
- `omnigent/server/routes/_session_create_validation.py` — load the pinned Bundle for Session validation.
- `omnigent/server/routes/_sessions/orchestration.py` — root snapshot capture, child snapshot inheritance, and Session-created projection hook.
- `omnigent/server/routes/_sessions/helpers.py` — Session status and durable relay-item projection hooks.
- `omnigent/server/routes/sessions/routes_events.py` — input/control event projection hooks after authoritative persistence.
- `omnigent/server/schemas.py` — Run request/response/Inspector and pinned Session response fields.
- `omnigent/server/app.py` — construct stores/services/projector and mount routes.
- `omnigent/server/routes/workspaces.py` — use an independent Workspace store and Agent-scoped thread defaults.
- `omnigent/workspaces/worktree_lease.py` — durable lease repository and Session/Attempt ownership.
- `omnigent/server/routes/_host_worktree.py` — persist lease lifecycle and recover it after restart.
- `omnigent/integrations/lark/router.py` — Agent binding and unified Run request.
- `omnigent/integrations/lark/adapter.py` — durable deduplication seam and Agent binding result.
- `omnigent/server/routes/feishu.py` — Agent-scoped install/status/delete/surface routes.
- `omnigent/server/routes/teams.py` — read-only compatibility diagnostics and `410 Gone` writes.

### Existing frontend files to modify

- `web/src/App.tsx` — remove Team Builder routes and keep `/runs/:runId` under Multi-Agent navigation.
- `web/src/shell/Sidebar.tsx` — remove Teams entry and classify Run pages as Multi-Agent.
- `web/src/components/runs/RunInspector.tsx` — render Agent/version/Digest and real Session links.
- `web/src/pages/RunInspectorPage.tsx` — return to Agent/Multi-Agent rather than Team.
- `web/src/pages/RunInspectorPage.test.tsx` — Agent-scoped navigation and response tests.

### Legacy files retained but removed from production execution wiring

- `omnigent/entities/team.py`
- `omnigent/teams/coordinator.py`
- `omnigent/teams/scheduler.py`
- `omnigent/teams/router.py`
- `omnigent/teams/reducer.py`
- `omnigent/teams/events.py`
- `web/src/pages/TeamsPage.tsx`
- `web/src/pages/TeamDetailPage.tsx`
- `web/src/components/teams/TeamForm.tsx`
- `web/src/components/teams/AgentProfileList.tsx`
- `web/src/hooks/useTeams.ts`
- `web/src/lib/teamsApi.ts`

They remain in the repository for legacy read diagnostics during this release, but `server/app.py`, `web/src/App.tsx`, and `web/src/shell/Sidebar.tsx` must not expose them as executable configuration.

---

### Task 1: Add immutable Agent Bundle snapshots and a multi-version AgentCache

**Files:**

- Modify: `omnigent/entities/agent.py`
- Modify: `omnigent/runtime/agent_cache.py`
- Modify: `tests/runtime/test_agent_cache.py`
- Modify: `tests/entities/test_agent.py`

- [ ] **Step 1: Write the failing Bundle snapshot tests**

Add to `tests/entities/test_agent.py`:

```python
import pytest

from omnigent.entities.agent import Agent, AgentBundleSnapshot


def test_agent_bundle_snapshot_uses_content_addressed_location() -> None:
    digest = "a" * 64
    agent = Agent(
        id="ag_snapshot",
        created_at=1,
        name="polly-copy",
        bundle_location=f"ag_snapshot/{digest}",
        version=7,
    )

    snapshot = AgentBundleSnapshot.from_agent(agent)

    assert snapshot.agent_id == "ag_snapshot"
    assert snapshot.bundle_version == 7
    assert snapshot.bundle_digest == digest
    assert snapshot.bundle_location == f"ag_snapshot/{digest}"


def test_agent_bundle_snapshot_rejects_non_digest_location() -> None:
    agent = Agent(
        id="ag_snapshot",
        created_at=1,
        name="broken",
        bundle_location="ag_snapshot/not-a-digest",
    )

    with pytest.raises(ValueError, match="content-addressed"):
        AgentBundleSnapshot.from_agent(agent)
```

- [ ] **Step 2: Write failing cache coexistence and eviction tests**

Add to `tests/runtime/test_agent_cache.py`, using the file's existing bundle builder and ArtifactStore fixture names where available:

```python
def test_same_agent_can_cache_two_bundle_digests(
    artifact_store: ArtifactStore,
    cache_dir: Path,
    make_bundle: Callable[[str], bytes],
) -> None:
    first = make_bundle("first-model")
    second = make_bundle("second-model")
    first_digest = hashlib.sha256(first).hexdigest()
    second_digest = hashlib.sha256(second).hexdigest()
    artifact_store.put(f"ag_multi/{first_digest}", first)
    artifact_store.put(f"ag_multi/{second_digest}", second)
    cache = AgentCache(artifact_store, cache_dir)

    loaded_first = cache.load("ag_multi", f"ag_multi/{first_digest}")
    loaded_second = cache.load("ag_multi", f"ag_multi/{second_digest}")

    assert loaded_first.workdir != loaded_second.workdir
    assert loaded_first.workdir.name == first_digest
    assert loaded_second.workdir.name == second_digest
    assert cache.load("ag_multi", f"ag_multi/{first_digest}").spec is loaded_first.spec


def test_evict_agent_removes_every_digest(
    artifact_store: ArtifactStore,
    cache_dir: Path,
    make_bundle: Callable[[str], bytes],
) -> None:
    bundles = [make_bundle("one"), make_bundle("two")]
    locations = []
    for bundle in bundles:
        digest = hashlib.sha256(bundle).hexdigest()
        location = f"ag_evict/{digest}"
        artifact_store.put(location, bundle)
        locations.append(location)
    cache = AgentCache(artifact_store, cache_dir)
    for location in locations:
        cache.load("ag_evict", location)

    cache.evict("ag_evict")

    assert not (cache_dir / "ag_evict").exists()
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/entities/test_agent.py tests/runtime/test_agent_cache.py -q
```

Expected: FAIL because `AgentBundleSnapshot` does not exist and both Digest loads currently resolve to `cache_dir/ag_multi`.

- [ ] **Step 4: Implement the Bundle snapshot value**

Add to `omnigent/entities/agent.py`:

```python
import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AgentBundleSnapshot:
    """Immutable identity of the Agent Bundle used by one Session tree."""

    agent_id: str
    bundle_version: int
    bundle_digest: str
    bundle_location: str

    @classmethod
    def from_agent(cls, agent: Agent) -> AgentBundleSnapshot:
        digest = agent.bundle_location.rsplit("/", 1)[-1]
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError("agent bundle_location is not content-addressed by SHA-256")
        return cls(
            agent_id=agent.id,
            bundle_version=agent.version,
            bundle_digest=digest,
            bundle_location=agent.bundle_location,
        )
```

Export `AgentBundleSnapshot` from `omnigent/entities/__init__.py` next to `Agent`.

- [ ] **Step 5: Change AgentCache identity to Agent plus Digest**

In `omnigent/runtime/agent_cache.py`, use the Bundle location Digest as part of both cache tiers:

```python
CacheKey = tuple[str, str, bool]


def _bundle_digest(bundle_location: str) -> str:
    digest = bundle_location.rsplit("/", 1)[-1]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("bundle_location must end in a SHA-256 digest")
    return digest
```

Change initialization and `load` to:

```python
self._specs: dict[CacheKey, AgentSpec] = {}

digest = _bundle_digest(bundle_location)
key = (agent_id, digest, expand_env)
workdir = self._cache_dir / agent_id / digest
if key in self._specs:
    return LoadedAgent(spec=self._specs[key], workdir=workdir)
if workdir.is_dir():
    spec = load_spec(workdir, expand_env=expand_env, prune_invalid_sub_agents=True)
    self._specs[key] = spec
    return LoadedAgent(spec=spec, workdir=workdir)
bundle_bytes = self._artifact_store.get(bundle_location)
return self._extract_and_cache(key, bundle_bytes, workdir, expand_env=expand_env)
```

Change `replace` to stage under the Digest directory without removing prior versions, and change `evict` to:

```python
def evict(self, agent_id: str) -> None:
    for key in tuple(self._specs):
        if key[0] == agent_id:
            self._specs.pop(key, None)
    agent_dir = self._cache_dir / agent_id
    if agent_dir.is_dir():
        shutil.rmtree(agent_dir)
```

Change `_extract_and_cache` to accept `key: CacheKey` and assign `self._specs[key] = spec`. Ensure `workdir.parent.mkdir(parents=True, exist_ok=True)` runs before extraction.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/entities/test_agent.py tests/runtime/test_agent_cache.py tests/server/test_builtin_bundles.py -q
```

Expected: PASS; the built-in seeding tests also prove `replace` and `evict` remain compatible.

- [ ] **Step 7: Commit**

```bash
git add omnigent/entities/agent.py omnigent/entities/__init__.py omnigent/runtime/agent_cache.py tests/entities/test_agent.py tests/runtime/test_agent_cache.py
git commit -m "feat(runtime): pin agent cache entries by bundle digest"
```

---

### Task 2: Persist and inherit the Bundle snapshot on every Conversation

**Files:**

- Modify: `omnigent/entities/conversation.py`
- Modify: `omnigent/db/db_models.py`
- Modify: `omnigent/db/converters.py`
- Modify: `omnigent/stores/conversation_store/__init__.py`
- Modify: `omnigent/stores/conversation_store/sqlalchemy_store.py`
- Modify: `omnigent/server/routes/_sessions/orchestration.py`
- Modify: `omnigent/server/routes/_session_create_validation.py`
- Modify: `omnigent/runner/session_init_protocol.py`
- Modify: `omnigent/server/schemas.py`
- Modify: `tests/stores/test_conversation_store.py`
- Modify: `tests/server/test_runner_session_init.py`
- Modify: `tests/server/routes/test_sessions_crud.py`

- [ ] **Step 1: Write failing Conversation inheritance tests**

Add to `tests/stores/test_conversation_store.py`:

```python
def test_child_inherits_parent_bundle_snapshot(conversation_store: ConversationStore) -> None:
    digest = "b" * 64
    root = conversation_store.create_conversation(
        agent_id="ag_tree",
        agent_bundle_version=4,
        agent_bundle_digest=digest,
        agent_bundle_location=f"ag_tree/{digest}",
    )

    child = conversation_store.create_conversation(
        kind="sub_agent",
        title="codex:auth-refactor",
        parent_conversation_id=root.id,
        agent_id="ag_tree",
        sub_agent_name="codex",
    )

    assert child.agent_bundle_version == 4
    assert child.agent_bundle_digest == digest
    assert child.agent_bundle_location == f"ag_tree/{digest}"


def test_child_rejects_bundle_snapshot_different_from_parent(
    conversation_store: ConversationStore,
) -> None:
    root = conversation_store.create_conversation(
        agent_id="ag_tree",
        agent_bundle_version=1,
        agent_bundle_digest="1" * 64,
        agent_bundle_location=f"ag_tree/{'1' * 64}",
    )

    with pytest.raises(ValueError, match="inherit the parent Bundle snapshot"):
        conversation_store.create_conversation(
            kind="sub_agent",
            title="codex:review",
            parent_conversation_id=root.id,
            agent_id="ag_tree",
            sub_agent_name="codex",
            agent_bundle_version=2,
            agent_bundle_digest="2" * 64,
            agent_bundle_location=f"ag_tree/{'2' * 64}",
        )
```

- [ ] **Step 2: Write the failing runner-init snapshot test**

Add to `tests/server/test_runner_session_init.py`:

```python
def test_runner_init_carries_pinned_bundle_snapshot() -> None:
    digest = "c" * 64
    conversation = make_conversation(
        agent_id="ag_runtime",
        agent_bundle_version=9,
        agent_bundle_digest=digest,
        agent_bundle_location=f"ag_runtime/{digest}",
    )

    payload = build_runner_session_init_payload(conversation, server_version="test")
    envelope = parse_runner_session_init_envelope(payload)

    assert envelope is not None
    assert envelope.bundle_version == 9
    assert envelope.bundle_digest == digest
    assert envelope.bundle_location == f"ag_runtime/{digest}"
```

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/stores/test_conversation_store.py tests/server/test_runner_session_init.py -q
```

Expected: FAIL because Conversation and Store signatures do not expose Bundle snapshot fields.

- [ ] **Step 4: Add Conversation and SQL model fields**

Add to `Conversation` in `omnigent/entities/conversation.py`:

```python
agent_bundle_version: int | None = None
agent_bundle_digest: str | None = None
agent_bundle_location: str | None = None
```

Add matching nullable columns to `SqlConversation` in `omnigent/db/db_models.py`:

```python
agent_bundle_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
agent_bundle_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
agent_bundle_location: Mapped[str | None] = mapped_column(String(512), nullable=True)
```

Update `omnigent/db/converters.py` to copy all three columns to `Conversation`.

- [ ] **Step 5: Extend the ConversationStore contract and enforce inheritance**

Add these keyword parameters to both Store declarations:

```python
agent_bundle_version: int | None = None,
agent_bundle_digest: str | None = None,
agent_bundle_location: str | None = None,
```

In `SqlAlchemyConversationStore.create_conversation`, after loading the parent row and before inserting the child, enforce:

```python
if parent_row is not None:
    inherited = (
        parent_row.agent_bundle_version,
        parent_row.agent_bundle_digest,
        parent_row.agent_bundle_location,
    )
    requested = (agent_bundle_version, agent_bundle_digest, agent_bundle_location)
    if any(value is not None for value in requested) and requested != inherited:
        raise ValueError("child Sessions must inherit the parent Bundle snapshot")
    agent_bundle_version, agent_bundle_digest, agent_bundle_location = inherited

if agent_id is not None and parent_conversation_id is None:
    if not all(
        value is not None
        for value in (agent_bundle_version, agent_bundle_digest, agent_bundle_location)
    ):
        raise ValueError("new Agent-bound root Sessions require a Bundle snapshot")
```

Pass all three values to the new `SqlConversation` row. Preserve nullable values when reading legacy rows.

- [ ] **Step 6: Capture root snapshots and use parent snapshots for child validation**

In `_create_session_from_existing_agent` in `omnigent/server/routes/_sessions/orchestration.py`:

```python
from omnigent.entities.agent import AgentBundleSnapshot

parent_conv: Conversation | None = None
if body.parent_session_id is not None:
    parent_conv = await asyncio.to_thread(
        conversation_store.get_conversation,
        body.parent_session_id,
    )

if parent_conv is None:
    bundle_snapshot = AgentBundleSnapshot.from_agent(agent)
else:
    if not all(
        (
            parent_conv.agent_bundle_version is not None,
            parent_conv.agent_bundle_digest is not None,
            parent_conv.agent_bundle_location is not None,
        )
    ):
        raise OmnigentError(
            "parent Session has no pinned Agent Bundle snapshot",
            code=ErrorCode.CONFLICT,
        )
    bundle_snapshot = AgentBundleSnapshot(
        agent_id=parent_conv.agent_id or agent.id,
        bundle_version=parent_conv.agent_bundle_version,
        bundle_digest=parent_conv.agent_bundle_digest,
        bundle_location=parent_conv.agent_bundle_location,
    )
```

Pass the snapshot to `create_conversation`. Change `_require_declared_subagent`, `_resolve_subagent_spec`, workspace validation, model validation, and Harness validation to load:

```python
agent_cache.load(
    bundle_snapshot.agent_id,
    bundle_snapshot.bundle_location,
    expand_env=agent.session_id is None,
)
```

instead of loading `agent.bundle_location` from the mutable Agent row.

- [ ] **Step 7: Extend runner init and API response schemas**

Add to `RunnerSessionInitEnvelope` in `omnigent/runner/session_init_protocol.py`:

```python
bundle_version: int
bundle_digest: str
bundle_location: str
```

Populate them from the Conversation and fail with `ValueError` if an Agent-bound current Session lacks the snapshot. Add optional `bundle_version` and `bundle_digest` fields to `SessionResponse` and `SessionListItem`; do not expose `bundle_location` in public list responses.

- [ ] **Step 8: Run Conversation, route, and protocol tests**

Run:

```bash
.venv/bin/pytest tests/stores/test_conversation_store.py tests/stores/test_conversation_store_split_db.py tests/server/test_runner_session_init.py tests/server/routes/test_sessions_crud.py -q
```

Expected: PASS, including split-database Conversation persistence.

- [ ] **Step 9: Commit**

```bash
git add omnigent/entities/conversation.py omnigent/db/db_models.py omnigent/db/converters.py omnigent/stores/conversation_store omnigent/server/routes/_sessions/orchestration.py omnigent/server/routes/_session_create_validation.py omnigent/runner/session_init_protocol.py omnigent/server/schemas.py tests/stores/test_conversation_store.py tests/server/test_runner_session_init.py tests/server/routes/test_sessions_crud.py
git commit -m "feat(sessions): persist immutable agent bundle snapshots"
```

---

### Task 3: Add the append-only migration for Session projections and compatibility

**Files:**

- Create: `omnigent/db/migrations/versions/zc1d2e3f4a5b_pin_bundle_and_project_sessions.py`
- Modify: `omnigent/db/db_models.py`
- Modify: `tests/db/test_team_harness_migration.py`
- Modify: `tests/db/test_migrations_sqlite_safe.py`

- [ ] **Step 1: Write failing migration tests for preservation and safe backfill**

Add to `tests/db/test_team_harness_migration.py`:

```python
def test_runtime_projection_migration_preserves_legacy_and_backfills_unique_agent(
    migrated_connection: Connection,
) -> None:
    digest = "d" * 64
    seed_legacy_team(
        migrated_connection,
        team_id="1" * 32,
        coordinator_profile_id="2" * 32,
        coordinator_name="Polly Copy",
        run_id="3" * 32,
    )
    seed_template_agent(
        migrated_connection,
        agent_id="4" * 32,
        name="Polly Copy",
        version=6,
        bundle_location=f"{'4' * 32}/{digest}",
    )

    upgrade_to("zc1d2e3f4a5b", migrated_connection)

    row = migrated_connection.execute(
        sa.text("SELECT team_id, agent_id, bundle_version, bundle_digest, legacy_state FROM runs")
    ).mappings().one()
    assert row == {
        "team_id": uuid_bytes("1" * 32),
        "agent_id": uuid_bytes("4" * 32),
        "bundle_version": 6,
        "bundle_digest": digest,
        "legacy_state": "legacy_bound",
    }


def test_runtime_projection_migration_leaves_ambiguous_team_unbound(
    migrated_connection: Connection,
) -> None:
    seed_legacy_team(
        migrated_connection,
        team_id="1" * 32,
        coordinator_profile_id="2" * 32,
        coordinator_name="Duplicated",
        run_id="3" * 32,
    )
    for agent_id in ("4" * 32, "5" * 32):
        seed_template_agent(
            migrated_connection,
            agent_id=agent_id,
            name="Duplicated",
            version=1,
            bundle_location=f"{agent_id}/{'e' * 64}",
        )

    upgrade_to("zc1d2e3f4a5b", migrated_connection)

    row = migrated_connection.execute(
        sa.text("SELECT agent_id, root_session_id, legacy_state FROM runs")
    ).mappings().one()
    assert row["agent_id"] is None
    assert row["root_session_id"] is None
    assert row["legacy_state"] == "legacy_unbound"
```

Add schema assertions for `feishu_thread_bindings` and `worktree_leases`, and assert no legacy Team table is dropped.

- [ ] **Step 2: Run migration tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/db/test_team_harness_migration.py tests/db/test_migrations_sqlite_safe.py -q
```

Expected: FAIL because revision `zc1d2e3f4a5b` and its columns/tables do not exist.

- [ ] **Step 3: Create the additive migration**

Create `omnigent/db/migrations/versions/zc1d2e3f4a5b_pin_bundle_and_project_sessions.py` with:

```python
"""Pin Session bundles and project real Session trees.

Revision ID: zc1d2e3f4a5b
Revises: zb2c3d4e5f6a
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision = "zc1d2e3f4a5b"
down_revision = "zb2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
            sa.Column("legacy_state", sa.String(32), nullable=False, server_default="legacy_unbound")
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
            "workspace_id", "installation_id", "chat_id", "thread_id",
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
            "workspace_id", "host_id", "worktree_path",
            name="uq_worktree_leases_host_path",
        ),
    )

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE runs SET legacy_state = 'legacy_unbound'"))
    _backfill_unique_agent_matches(connection)


def _backfill_unique_agent_matches(connection: sa.Connection) -> None:
    rows = connection.execute(sa.text("""
        SELECT r.workspace_id, r.id AS run_id, p.name AS coordinator_name
        FROM runs r
        JOIN teams t ON t.workspace_id = r.workspace_id AND t.id = r.team_id
        JOIN agent_profiles p
          ON p.workspace_id = t.workspace_id AND p.id = t.coordinator_id
    """)).mappings()
    for row in rows:
        matches = connection.execute(sa.text("""
            SELECT id, version, bundle_location
            FROM agents
            WHERE workspace_id = :workspace_id AND kind = 1 AND LOWER(name) = LOWER(:name)
        """), {"workspace_id": row["workspace_id"], "name": row["coordinator_name"]}).mappings().all()
        if len(matches) != 1:
            continue
        match = matches[0]
        digest = str(match["bundle_location"]).rsplit("/", 1)[-1]
        if len(digest) != 64:
            continue
        connection.execute(sa.text("""
            UPDATE runs
            SET agent_id = :agent_id,
                bundle_version = :bundle_version,
                bundle_digest = :bundle_digest,
                legacy_state = 'legacy_bound'
            WHERE workspace_id = :workspace_id AND id = :run_id
        """), {
            "agent_id": match["id"],
            "bundle_version": match["version"],
            "bundle_digest": digest,
            "workspace_id": row["workspace_id"],
            "run_id": row["run_id"],
        })
```

Create each new index in the repository's required migration style. If this Alembic repository supports `CREATE INDEX CONCURRENTLY`, place every PostgreSQL concurrent index in its own single-statement follow-up revision; for SQLite test runs, use the migration helper already exercised by `tests/db/test_migrations_sqlite_safe.py`. Required indexes are:

```text
ix_runs_agent_status(workspace_id, agent_id, status, id)
uq_runs_root_session(workspace_id, root_session_id)
uq_run_tasks_source_event(workspace_id, source_event_id)
uq_attempts_source_event(workspace_id, source_event_id)
uq_harness_events_source(workspace_id, source_kind, source_event_id)
ix_feishu_installations_agent_id(workspace_id, agent_id, id)
ix_feishu_thread_bindings_agent(workspace_id, agent_id, id)
ix_worktree_leases_child(workspace_id, child_session_id, state, id)
```

The downgrade drops only new indexes/tables/columns and restores the two legacy columns to non-null after deleting no legacy rows. It must reject downgrade when new native rows have null `team_id` or `agent_profile_id`, with an actionable exception instead of fabricating IDs.

- [ ] **Step 4: Add matching SQLAlchemy models**

Update `SqlRun`, `SqlRunTask`, `SqlAttempt`, `SqlHarnessEvent`, and `SqlFeishuInstallation` with the exact migration columns. Add `SqlFeishuThreadBinding` and `SqlWorktreeLease`. Do not add database foreign keys or cascade actions.

- [ ] **Step 5: Run migration tests and inspect heads**

Run:

```bash
.venv/bin/pytest tests/db/test_team_harness_migration.py tests/db/test_migrations_sqlite_safe.py -q
.venv/bin/alembic -c omnigent/db/alembic.ini heads
```

Expected: PASS and exactly one Alembic head descending from `zc1d2e3f4a5b` or its required index-only follow-up revisions.

- [ ] **Step 6: Commit**

```bash
git add omnigent/db/db_models.py omnigent/db/migrations/versions tests/db/test_team_harness_migration.py tests/db/test_migrations_sqlite_safe.py
git commit -m "feat(db): add session-backed run projection schema"
```

---

### Task 4: Implement the RunStore and stable Inspector records

**Files:**

- Create: `omnigent/entities/run_projection.py`
- Create: `omnigent/stores/run_store/__init__.py`
- Create: `omnigent/stores/run_store/sqlalchemy_store.py`
- Create: `tests/stores/test_run_store.py`
- Modify: `omnigent/entities/__init__.py`
- Modify: `omnigent/stores/__init__.py`

- [ ] **Step 1: Write failing RunStore tests**

Create `tests/stores/test_run_store.py`:

```python
from omnigent.entities.agent import AgentBundleSnapshot
from omnigent.entities.run_projection import AttemptProjectionInput, DispatchProjectionInput
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore


def test_create_run_pins_bundle_and_workspace(database_url: str) -> None:
    store = SqlAlchemyRunStore(database_url)
    snapshot = AgentBundleSnapshot(
        agent_id="ag_polly",
        bundle_version=3,
        bundle_digest="a" * 64,
        bundle_location=f"ag_polly/{'a' * 64}",
    )

    run = store.create_run(
        snapshot=snapshot,
        workspace_bundle_id="1" * 32,
        source="web",
        source_event_id="web:request-1",
    )
    store.bind_root_session(run.id, "2" * 32)

    restored = store.get_run(run.id)
    assert restored is not None
    assert restored.agent_id == "ag_polly"
    assert restored.bundle_version == 3
    assert restored.bundle_digest == "a" * 64
    assert restored.workspace_id == "1" * 32
    assert restored.root_session_id == "2" * 32


def test_project_dispatch_is_idempotent_but_new_turn_creates_new_attempt(
    run_store: SqlAlchemyRunStore,
    native_run_id: str,
) -> None:
    dispatch = DispatchProjectionInput(
        source_event_id="item-call-1",
        root_session_id="2" * 32,
        child_session_id="3" * 32,
        title="auth-refactor",
        worker_name="codex",
        worker_config_path="agents/codex/config.yaml",
        purpose="implement",
        harness="codex-native",
        model="gpt-5.6-sol",
        dispatch_call_id="call-1",
        response_id="response-1",
        occurred_at=100,
    )

    first = run_store.project_dispatch(native_run_id, dispatch)
    replay = run_store.project_dispatch(native_run_id, dispatch)
    second_turn = run_store.project_dispatch(
        native_run_id,
        dataclasses.replace(
            dispatch,
            source_event_id="item-call-2",
            dispatch_call_id="call-2",
            response_id="response-2",
            occurred_at=200,
        ),
    )

    assert first.task.id == replay.task.id == second_turn.task.id
    assert first.attempt.id == replay.attempt.id
    assert second_turn.attempt.id != first.attempt.id
    assert len(run_store.get_inspector(native_run_id).attempts) == 2
```

Add a test proving `add_dependency` requires an explicit dependency event and never derives a dependency from timestamps.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/stores/test_run_store.py -q
```

Expected: FAIL because the projection entities and RunStore do not exist.

- [ ] **Step 3: Define stable projection entities**

Create `omnigent/entities/run_projection.py` with frozen dataclasses and no execution methods:

```python
@dataclass(frozen=True)
class RunRecord:
    id: str
    agent_id: str | None
    bundle_version: int | None
    bundle_digest: str | None
    workspace_id: str | None
    root_session_id: str | None
    source: str
    status: str
    legacy_state: str
    created_at: int
    updated_at: int | None


@dataclass(frozen=True)
class DispatchProjectionInput:
    source_event_id: str
    root_session_id: str
    child_session_id: str
    title: str
    worker_name: str
    worker_config_path: str
    purpose: str
    harness: str | None
    model: str | None
    dispatch_call_id: str
    response_id: str | None
    occurred_at: int


@dataclass(frozen=True)
class ProjectionResult:
    task: TaskRecord
    attempt: AttemptRecord
    created: bool


@dataclass(frozen=True)
class RunInspectorRecord:
    run: RunRecord
    tasks: tuple[TaskRecord, ...]
    attempts: tuple[AttemptRecord, ...]
    events: tuple[ProjectionEventRecord, ...]
    artifacts: tuple[ArtifactProjectionRecord, ...]
```

Also define complete `TaskRecord`, `AttemptRecord`, `ProjectionEventRecord`, `ArtifactProjectionRecord`, `AttemptTerminalInput`, and `ExplicitDependencyInput` dataclasses matching the Task 3 columns.

- [ ] **Step 4: Define the RunStore protocol**

Create `omnigent/stores/run_store/__init__.py` with:

```python
class RunNotFoundError(LookupError):
    pass


class RunConflictError(RuntimeError):
    pass


class RunStore(Protocol):
    def create_run(
        self,
        *,
        snapshot: AgentBundleSnapshot,
        workspace_bundle_id: str | None,
        source: str,
        source_event_id: str,
    ) -> RunRecord: ...

    def bind_root_session(self, run_id: str, root_session_id: str) -> RunRecord: ...
    def find_by_root_session(self, root_session_id: str) -> RunRecord | None: ...
    def find_by_session(self, session_id: str) -> RunRecord | None: ...
    def project_dispatch(self, run_id: str, event: DispatchProjectionInput) -> ProjectionResult: ...
    def complete_attempt(self, run_id: str, event: AttemptTerminalInput) -> AttemptRecord: ...
    def add_explicit_dependency(self, run_id: str, event: ExplicitDependencyInput) -> None: ...
    def get_run(self, run_id: str) -> RunRecord | None: ...
    def get_inspector(self, run_id: str) -> RunInspectorRecord: ...
    def list_agent_runs(self, agent_id: str, *, limit: int, cursor: str | None) -> Page[RunRecord]: ...
```

- [ ] **Step 5: Implement transactional SQL idempotency**

In `SqlAlchemyRunStore`:

- use `make_managed_session_maker(get_or_create_engine(storage_location))`;
- make `source_event_id` the idempotency boundary;
- use one transaction to insert the Task, Attempt, and Harness event;
- identify a logical Task by `(run_id, child_session_id, dispatch_title)`;
- identify an Attempt by `source_event_id`, not only by Child Session;
- allocate event sequence with an atomic workspace-scoped allocator rather than `MAX(sequence)+1`;
- reject `bind_root_session` when a different root is already stored;
- reject workspace or Bundle mutation once `root_session_id` is bound;
- return references to Session IDs and item IDs, not copied transcript bodies.

The minimal transaction shape is:

```python
with self._session() as session:
    existing_event = session.execute(
        select(SqlHarnessEvent).where(
            SqlHarnessEvent.workspace_id == current_workspace_id(),
            SqlHarnessEvent.source_kind == "session.dispatch",
            SqlHarnessEvent.source_event_id == event.source_event_id,
        )
    ).scalar_one_or_none()
    if existing_event is not None:
        return self._projection_result_for_event(session, existing_event, created=False)

    task = self._get_or_create_task(session, run_id, event)
    attempt = SqlAttempt(
        id=uuid4().hex,
        task_id=task.id,
        child_session_id=event.child_session_id,
        worker_name=event.worker_name,
        worker_config_path=event.worker_config_path,
        purpose=event.purpose,
        harness=event.harness,
        model=event.model,
        dispatch_call_id=event.dispatch_call_id,
        response_id=event.response_id,
        started_at=event.occurred_at,
        status="running",
        source_event_id=event.source_event_id,
        created_at=event.occurred_at,
    )
    session.add(attempt)
    projection_event = self._append_projection_event(
        session,
        run_id=run_id,
        task_id=task.id,
        attempt_id=attempt.id,
        session_id=event.child_session_id,
        source_kind="session.dispatch",
        source_event_id=event.source_event_id,
        event_type="attempt.started",
        occurred_at=event.occurred_at,
    )
    session.flush()
    return self._projection_result(task, attempt, created=True)
```

- [ ] **Step 6: Run Store tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/stores/test_run_store.py -q
```

Expected: PASS, including duplicate Dispatch replay and same Child Session/new turn behavior.

- [ ] **Step 7: Commit**

```bash
git add omnigent/entities/run_projection.py omnigent/entities/__init__.py omnigent/stores/run_store omnigent/stores/__init__.py tests/stores/test_run_store.py
git commit -m "feat(runs): add session projection store"
```

---

### Task 5: Project real Session lifecycle events without creating a second engine

**Files:**

- Create: `omnigent/runs/__init__.py`
- Create: `omnigent/runs/projection.py`
- Create: `tests/runs/test_projection.py`
- Create: `tests/server/integration/test_run_projection.py`
- Modify: `omnigent/server/routes/_sessions/orchestration.py`
- Modify: `omnigent/server/routes/_sessions/helpers.py`
- Modify: `omnigent/server/routes/sessions/routes_events.py`
- Modify: `omnigent/server/app.py`

- [ ] **Step 1: Write pure projector tests for recognized events**

Create `tests/runs/test_projection.py`:

```python
def test_sys_session_send_call_projects_dispatch(run_store: FakeRunStore) -> None:
    projector = SessionRunProjector(run_store)
    projector.project_item(
        SessionItemProjection(
            item_id="item-call-1",
            session_id="root-1",
            root_session_id="root-1",
            response_id="response-1",
            item_type="function_call",
            data={
                "name": "sys_session_send",
                "call_id": "call-1",
                "arguments": json.dumps({
                    "agent": "codex",
                    "title": "auth-refactor",
                    "args": {"input": "implement auth", "purpose": "implement", "model": "gpt-5.6-sol"},
                }),
            },
            occurred_at=10,
        )
    )
    projector.project_session_created(
        SessionCreatedProjection(
            source_event_id="session:child-1:created",
            session_id="child-1",
            root_session_id="root-1",
            parent_session_id="root-1",
            title="codex:auth-refactor",
            sub_agent_name="codex",
            harness="codex-native",
            model="gpt-5.6-sol",
            occurred_at=11,
        )
    )

    dispatch = run_store.dispatches[0]
    assert dispatch.worker_name == "codex"
    assert dispatch.title == "auth-refactor"
    assert dispatch.purpose == "implement"
    assert dispatch.child_session_id == "child-1"


def test_projector_does_not_invent_dependency_from_event_order(
    run_store: FakeRunStore,
) -> None:
    projector = SessionRunProjector(run_store)
    project_two_dispatches(projector, occurred_at=(10, 20))

    assert run_store.dependencies == []
```

Add cases for:

- `external_session_status=idle` → attempt succeeded;
- `external_session_status=failed` plus ErrorData → attempt failed with stable failure code;
- Worker boot failure;
- Parent Inbox completion reference;
- explicit plan dependency event;
- resource/artifact event;
- replay of any source event remains a no-op.

- [ ] **Step 2: Run pure tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/runs/test_projection.py -q
```

Expected: FAIL because `SessionRunProjector` and typed projection inputs do not exist.

- [ ] **Step 3: Implement a projector with observation-only methods**

Create `omnigent/runs/projection.py` with:

```python
class SessionRunProjector:
    """Idempotently project authoritative Session events into Run read models."""

    def __init__(self, store: RunStore) -> None:
        self._store = store
        self._pending_dispatches: dict[tuple[str, str, str], SessionItemProjection] = {}

    def project_session_created(self, event: SessionCreatedProjection) -> None:
        run = self._store.find_by_root_session(event.root_session_id)
        if run is None or event.parent_session_id is None:
            return
        worker, title = self._split_child_title(event)
        pending = self._pending_dispatches.pop(
            (event.parent_session_id, worker, title),
            None,
        )
        if pending is None:
            return
        args = self._sys_session_send_args(pending)
        self._store.project_dispatch(
            run.id,
            DispatchProjectionInput(
                source_event_id=pending.item_id,
                root_session_id=event.root_session_id,
                child_session_id=event.session_id,
                title=title,
                worker_name=worker,
                worker_config_path=f"agents/{worker}/config.yaml",
                purpose=str(args.get("purpose", "implement")),
                harness=event.harness,
                model=event.model,
                dispatch_call_id=str(pending.data["call_id"]),
                response_id=pending.response_id,
                occurred_at=event.occurred_at,
            ),
        )

    def project_item(self, event: SessionItemProjection) -> None:
        if not self._is_sys_session_send(event):
            self._project_artifact_or_error(event)
            return
        args = self._sys_session_send_args(event)
        key = (event.session_id, str(args["agent"]), str(args["title"]))
        self._pending_dispatches[key] = event

    def project_status(self, event: SessionStatusProjection) -> None:
        run = self._store.find_by_session(event.session_id)
        if run is None:
            return
        self._store.complete_attempt(
            run.id,
            AttemptTerminalInput.from_status(event),
        )
```

The class must not import `Coordinator`, `DAGScheduler`, `ParentInbox`, runner launch helpers, or `sys_session_send` execution functions. Its imports are restricted to entities, `RunStore`, `json`, and logging.

- [ ] **Step 4: Add projection hooks after authoritative writes**

Wire one `SessionRunProjector` instance through `create_app` and app state.

In `_create_session_from_existing_agent`, call `project_session_created` only after `conversation_store.create_conversation` succeeds.

In `_relay_persist` and `_relay_persist_error_once`, capture the returned persisted item and call `project_item` only after append succeeds. Adjust the helper return value from `None` to `ConversationItem | None` so the stable store-assigned item ID is available.

In `routes_events.py`, call the projector only after an item/control event has reached its existing authoritative persistence/forward boundary. Do not project pre-validation or denied requests as successful dispatches.

In `_publish_status`, call `project_status` after `persist_live_status`. The projector must receive the current Conversation and stable response/error metadata; a failed projection is logged and retried from durable Session state, but it does not suppress the real Session status event.

- [ ] **Step 5: Write the real persistence integration test**

Create `tests/server/integration/test_run_projection.py`:

```python
async def test_real_session_items_and_status_build_run_projection(
    app_client: httpx.AsyncClient,
    run_store: SqlAlchemyRunStore,
    template_agent: Agent,
) -> None:
    created = await app_client.post(
        "/v1/runs",
        json={"agent_id": template_agent.id, "source": "test", "input": "implement auth"},
    )
    assert created.status_code == 201
    run = created.json()
    root_id = run["root_session_id"]

    await post_runner_item(
        app_client,
        root_id,
        function_call_item(
            item_id="item-call-1",
            name="sys_session_send",
            call_id="call-1",
            arguments={
                "agent": "codex",
                "title": "auth-refactor",
                "args": {"input": "implement", "purpose": "implement"},
            },
        ),
    )
    child = await create_named_child(
        app_client,
        parent_session_id=root_id,
        agent_id=template_agent.id,
        sub_agent_name="codex",
        title="codex:auth-refactor",
    )
    await post_external_status(app_client, child["id"], "idle")

    inspector = run_store.get_inspector(run["id"])
    assert len(inspector.tasks) == 1
    assert len(inspector.attempts) == 1
    assert inspector.attempts[0].child_session_id == child["id"]
    assert inspector.attempts[0].status == "succeeded"
```

- [ ] **Step 6: Run unit and integration tests**

Run:

```bash
.venv/bin/pytest tests/runs/test_projection.py tests/server/integration/test_run_projection.py -q
```

Expected: PASS. Inspect imports with:

```bash
rg -n 'Coordinator|DAGScheduler|ParentInbox|schedule\(' omnigent/runs
```

Expected: no matches.

- [ ] **Step 7: Commit**

```bash
git add omnigent/runs omnigent/server/routes/_sessions/orchestration.py omnigent/server/routes/_sessions/helpers.py omnigent/server/routes/sessions/routes_events.py omnigent/server/app.py tests/runs/test_projection.py tests/server/integration/test_run_projection.py
git commit -m "feat(runs): project real session lifecycle events"
```

---

### Task 6: Add one unified Run service and authenticated API

**Files:**

- Create: `omnigent/runs/service.py`
- Create: `omnigent/server/routes/runs.py`
- Create: `tests/runs/test_service.py`
- Create: `tests/server/test_runs_routes.py`
- Modify: `omnigent/server/schemas.py`
- Modify: `omnigent/server/app.py`
- Modify: `omnigent/server/routes/_sessions/orchestration.py`

- [ ] **Step 1: Write failing Run service tests for atomic snapshot selection**

Create `tests/runs/test_service.py`:

```python
async def test_create_run_uses_one_agent_snapshot_for_run_and_root_session(
    run_service: RunService,
    agent_store: AgentStore,
) -> None:
    agent = create_template_agent(agent_store, version=5, digest="a" * 64)

    created = await run_service.create(
        RunCreateCommand(
            agent_id=agent.id,
            workspace_id=None,
            source="web",
            source_event_id="web:req-1",
            input_text="implement auth",
            actor_id="user-1",
        )
    )

    assert created.run.bundle_version == 5
    assert created.run.bundle_digest == "a" * 64
    assert created.root_session.agent_bundle_version == 5
    assert created.root_session.agent_bundle_digest == "a" * 64


async def test_duplicate_source_event_returns_existing_run(run_service: RunService) -> None:
    command = make_run_command(source_event_id="feishu:event-1")

    first = await run_service.create(command)
    replay = await run_service.create(command)

    assert replay.run.id == first.run.id
    assert replay.root_session.id == first.root_session.id
    assert replay.created is False
```

Add a failure test proving Session creation failure removes the unbound provisional Run or marks it `failed` with the exact creation error; it must never return a Run without a root Session as accepted.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/runs/test_service.py -q
```

Expected: FAIL because `RunService` and `RunCreateCommand` do not exist.

- [ ] **Step 3: Implement the single Run creation command**

Create `omnigent/runs/service.py`:

```python
@dataclass(frozen=True)
class RunCreateCommand:
    agent_id: str
    workspace_id: str | None
    source: str
    source_event_id: str
    input_text: str
    actor_id: str | None
    host_id: str | None = None
    execution_mode: str = "auto"


@dataclass(frozen=True)
class CreatedRun:
    run: RunRecord
    root_session: Conversation
    created: bool


class RunService:
    def __init__(
        self,
        *,
        agent_store: AgentStore,
        run_store: RunStore,
        session_creator: SessionCreator,
        session_input: SessionInputSender,
        workspace_store: WorkspaceStore,
    ) -> None:
        self._agent_store = agent_store
        self._run_store = run_store
        self._session_creator = session_creator
        self._session_input = session_input
        self._workspace_store = workspace_store

    async def create(self, command: RunCreateCommand) -> CreatedRun:
        existing = self._run_store.find_by_source_event(command.source, command.source_event_id)
        if existing is not None:
            root = self._require_root(existing)
            return CreatedRun(existing, root, created=False)
        agent = await asyncio.to_thread(self._agent_store.get, command.agent_id)
        if agent is None or agent.session_id is not None:
            raise RunNotFoundError("Run Agent must be a durable template")
        snapshot = AgentBundleSnapshot.from_agent(agent)
        workspace = self._workspace_store.resolve_for_run(command.workspace_id)
        run = self._run_store.create_run(
            snapshot=snapshot,
            workspace_bundle_id=workspace.id if workspace else None,
            source=command.source,
            source_event_id=command.source_event_id,
        )
        try:
            root = await self._session_creator.create_root(
                snapshot=snapshot,
                workspace=workspace,
                host_id=command.host_id,
                execution_mode=command.execution_mode,
            )
            self._run_store.bind_root_session(run.id, root.id)
            await self._session_input.send(root.id, command.input_text, command.actor_id)
        except Exception as exc:
            self._run_store.fail_creation(run.id, failure_code="ROOT_SESSION_CREATE_FAILED", error=exc)
            raise
        return CreatedRun(self._run_store.get_required(run.id), root, created=True)
```

`SessionCreator` and `SessionInputSender` are narrow protocols backed by existing Session route orchestration helpers; they must not reimplement Session creation or task execution.

- [ ] **Step 4: Define API schemas and routes**

Add to `omnigent/server/schemas.py`:

```python
class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    workspace_id: str | None = None
    input: str = Field(min_length=1, max_length=200_000)
    source: Literal["web", "feishu", "scheduled", "api"] = "web"
    source_event_id: str | None = Field(default=None, max_length=256)
    host_id: str | None = None
    execution_mode: Literal["auto", "cautious", "read_only"] = "auto"


class RunResponse(BaseModel):
    id: str
    agent_id: str | None
    bundle_version: int | None
    bundle_digest: str | None
    workspace_id: str | None
    root_session_id: str | None
    source: str
    status: str
    legacy_state: str
```

Create `omnigent/server/routes/runs.py` with authenticated routes:

```python
@router.post("/runs", response_model=RunResponse, status_code=201)
async def create_run(request: Request, body: RunCreateRequest) -> RunResponse:
    user = require_user(request, auth_provider)
    source_event_id = body.source_event_id or f"web:{uuid4().hex}"
    created = await service.create(
        RunCreateCommand(
            agent_id=body.agent_id,
            workspace_id=body.workspace_id,
            source=body.source,
            source_event_id=source_event_id,
            input_text=body.input,
            actor_id=user.user_id if user is not None else None,
            host_id=body.host_id,
            execution_mode=body.execution_mode,
        )
    )
    return RunResponse.model_validate(created.run, from_attributes=True)


@router.get("/agents/{agent_id}/runs")
async def list_agent_runs(...): ...


@router.get("/runs/{run_id}")
async def get_run(...): ...


@router.get("/runs/{run_id}/events")
async def list_run_events(...): ...
```

Implement the three GET handlers using `RunStore`, membership/auth checks, explicit `limit` bounds of 1–200, opaque cursor handling, and response models. The `get_run` route returns the Inspector DTO introduced in Task 10, not a raw ORM object.

- [ ] **Step 5: Write route contract tests**

Create `tests/server/test_runs_routes.py` covering:

```python
async def test_post_run_returns_pinned_root(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/runs",
        json={"agent_id": "ag_polly", "input": "implement auth", "source": "web"},
    )
    assert response.status_code == 201
    assert response.json()["root_session_id"]
    assert response.json()["bundle_version"] == 3
    assert response.json()["bundle_digest"] == "a" * 64


async def test_run_workspace_cannot_change_after_root_is_bound(
    client: httpx.AsyncClient,
) -> None:
    run = await create_run(client, workspace_id="1" * 32)
    response = await client.post(
        f"/v1/workspaces/{'2' * 32}/select",
        json={"thread_id": "web", "run_id": run["id"]},
    )
    assert response.status_code == 409
```

Also test 404 Agent, session-scoped Agent rejection, duplicate source event, auth denial, event pagination, and malformed response serialization.

- [ ] **Step 6: Mount the Run router and remove the legacy `/runs/{id}` collision**

In `server/app.py`, construct `SqlAlchemyRunStore`, `SessionRunProjector`, and `RunService`, place them on `app.state`, and mount `create_runs_router` under `/v1` before compatibility Team routes. Remove `/runs/{run_id}` from `create_teams_router` so only one handler owns that path.

- [ ] **Step 7: Run service and route tests**

Run:

```bash
.venv/bin/pytest tests/runs/test_service.py tests/server/test_runs_routes.py tests/server/test_team_routes.py -q
```

Expected: PASS; `/v1/runs/{id}` is served only by the new Run router.

- [ ] **Step 8: Commit**

```bash
git add omnigent/runs/service.py omnigent/server/routes/runs.py omnigent/server/schemas.py omnigent/server/app.py omnigent/server/routes/_sessions/orchestration.py tests/runs/test_service.py tests/server/test_runs_routes.py
git commit -m "feat(runs): add unified agent run service"
```

---

### Task 7: Make Workspace selection and multi-repository worktree leases Run-native

**Files:**

- Modify: `omnigent/server/routes/workspaces.py`
- Modify: `omnigent/server/routes/teams.py`
- Modify: `omnigent/workspaces/worktree_lease.py`
- Modify: `omnigent/server/routes/_host_worktree.py`
- Modify: `omnigent/server/routes/_sessions/helpers.py`
- Modify: `omnigent/server/routes/_sessions/orchestration.py`
- Modify: `tests/teams/test_workspace_registry.py`
- Modify: `tests/teams/test_multirepo_worktree_lease.py`
- Modify: `tests/server/test_team_routes.py`

- [ ] **Step 1: Write failing Agent-scoped selection and durable lease tests**

Add to `tests/server/test_team_routes.py`:

```python
async def test_thread_workspace_defaults_are_scoped_by_agent(client: httpx.AsyncClient) -> None:
    first, second = await create_two_workspaces(client)

    await client.post(
        f"/v1/workspaces/{first['id']}/select",
        json={"thread_id": "chat-1", "agent_id": "1" * 32},
    )
    await client.post(
        f"/v1/workspaces/{second['id']}/select",
        json={"thread_id": "chat-1", "agent_id": "2" * 32},
    )

    assert await selected_workspace(client, "chat-1", "1" * 32) == first["id"]
    assert await selected_workspace(client, "chat-1", "2" * 32) == second["id"]
```

Add to `tests/teams/test_multirepo_worktree_lease.py`:

```python
async def test_lease_survives_manager_restart(
    database_url: str,
    fake_host: FakeHostConnection,
) -> None:
    first = WorktreeLeaseManager(SqlAlchemyWorktreeLeaseStore(database_url))
    leases = await first.acquire(
        host_id="host-1",
        host_registry=fake_host.registry,
        host_conn=fake_host.connection,
        workspace_root=fake_host.root,
        repositories=(repo("api"), repo("core")),
        child_session_id="1" * 32,
        attempt_id="2" * 32,
        owner_id="runner-1",
    )

    restored = WorktreeLeaseManager(SqlAlchemyWorktreeLeaseStore(database_url))

    assert {lease.id for lease in restored.active(host_id="host-1")} == {
        lease.id for lease in leases
    }
```

Add a test that two Child Sessions using the same Worker name but different titles receive different worktree paths and branches for every writable repository.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/server/test_team_routes.py tests/teams/test_multirepo_worktree_lease.py -q
```

Expected: FAIL because selection is only thread-scoped and lease records are in process memory.

- [ ] **Step 3: Separate Workspace storage from Team storage**

Extract Workspace methods currently embedded in `TeamMemoryStore`/`SqlAlchemyTeamWorkspaceStore` into a `WorkspaceStore` protocol and SQL implementation under `omnigent/workspaces/registry.py` or a focused `omnigent/stores/workspace_store.py` following existing Store patterns.

Change `SelectWorkspaceRequest` to include:

```python
agent_id: str
thread_id: str
run_id: str | None = None
```

Persist the Agent scope in `SqlThreadWorkspaceSelection.scope` as `f"agent:{agent_id}"`. Keep `scope=""` readable as a legacy fallback only when no Agent-scoped value exists; every new write uses the Agent scope.

When `run_id` is present, `WorkspaceStore` asks `RunStore.assert_workspace_mutable(run_id, workspace_id)`. A Run with `root_session_id` or status outside `queued` rejects a different Workspace with `RunConflictError`.

- [ ] **Step 4: Persist lease lifecycle**

Add `SqlAlchemyWorktreeLeaseStore` with methods:

```python
create_many(leases: Sequence[WorktreeLease]) -> tuple[WorktreeLease, ...]
heartbeat(ids: Sequence[str], owner_id: str, now: int) -> None
list_active(host_id: str | None = None) -> tuple[WorktreeLease, ...]
mark_released(ids: Sequence[str], owner_id: str, released_at: int) -> None
mark_expired(ids: Sequence[str], now: int) -> None
```

Change `WorktreeLeaseManager` to require this Store and replace `_records` reads/writes with Store calls. Keep the existing per-repository locks around host operations. Acquisition order is:

```text
validate all repositories
→ create host worktrees
→ persist all leases in one transaction
→ on persistence failure remove every created host worktree
→ return persisted leases
```

Release order is:

```text
verify owner
→ remove host worktrees
→ atomically mark leases released
```

- [ ] **Step 5: Bind leases to real Child Sessions**

Remove public caller authority over arbitrary `attempt_id`/`lease_owner_id`. The internal Session creation adapter derives:

```python
child_session_id = reserved_conversation_id
owner_id = inherited_runner_id or f"session:{child_session_id}"
```

Reserve the Child Conversation ID before worktree acquisition, then pass it through `conversation_store.create_conversation(conversation_id=...)`. After the projector creates the Attempt, update the lease rows with the Attempt ID. A failed Session create releases all leases using the existing rollback path.

For a multi-repository Workspace, acquire one lease per writable repository and store the repository-to-worktree map as Session runtime context; do not flatten the Workspace root into a fake Git repository.

- [ ] **Step 6: Run Workspace and lease tests**

Run:

```bash
.venv/bin/pytest tests/teams/test_workspace_registry.py tests/teams/test_multirepo_worktree_lease.py tests/server/test_team_routes.py -q
```

Expected: PASS, including restart recovery and same Worker/different title isolation.

- [ ] **Step 7: Commit**

```bash
git add omnigent/server/routes/workspaces.py omnigent/server/routes/teams.py omnigent/workspaces omnigent/server/routes/_host_worktree.py omnigent/server/routes/_sessions/helpers.py omnigent/server/routes/_sessions/orchestration.py tests/teams/test_workspace_registry.py tests/teams/test_multirepo_worktree_lease.py tests/server/test_team_routes.py
git commit -m "feat(workspaces): bind durable leases to session attempts"
```

---

### Task 8: Replace Team-scoped Feishu routing with durable Agent bindings

**Files:**

- Create: `omnigent/integrations/lark/store.py`
- Modify: `omnigent/integrations/lark/router.py`
- Modify: `omnigent/integrations/lark/adapter.py`
- Modify: `omnigent/server/routes/feishu.py`
- Modify: `omnigent/server/app.py`
- Modify: `tests/server/test_feishu_routes.py`
- Modify: `tests/integrations/lark/test_adapter_router.py`
- Modify: `tests/integrations/lark/test_surface.py`
- Modify: `web/src/lib/feishuApi.ts`
- Modify: `web/src/hooks/useFeishuInstall.ts`
- Modify: `web/src/hooks/useFeishuInstall.test.tsx`

- [ ] **Step 1: Write failing Agent-scoped route tests**

Add to `tests/server/test_feishu_routes.py`:

```python
def test_agent_scoped_installation_persists_binding_and_hides_secret() -> None:
    client, store = agent_scoped_client(agent_id="ag_polly")

    begin = client.post("/v1/agents/ag_polly/feishu/installations")
    assert begin.status_code == 200
    completed = client.get(
        f"/v1/agents/ag_polly/feishu/installations/{begin.json()['session']}"
    )

    assert completed.status_code == 200
    assert completed.json()["agent_id"] == "ag_polly"
    assert "secret" not in completed.text.lower()
    assert store.get_for_agent("ag_polly").app_secret_ciphertext


def test_agent_scoped_install_rejects_builtin_template() -> None:
    client, _ = agent_scoped_client(agent_id="ag_builtin", builtin=True)

    response = client.post("/v1/agents/ag_builtin/feishu/installations")

    assert response.status_code == 409
    assert "clone" in response.json()["detail"].lower()
```

Add route tests for GET status, DELETE disconnect, Surface reinitialize, Agent mismatch on poll, and restart persistence.

- [ ] **Step 2: Write failing inbound routing and idempotency tests**

Add to `tests/integrations/lark/test_adapter_router.py`:

```python
def test_worker_mention_still_creates_root_agent_run() -> None:
    service = FakeRunService()
    router = LarkRouter(binding_store=bound_agent_store("ag_polly"), run_service=service)

    result = router.route_message(
        LarkMessage(
            event_id="event-1",
            chat_id="chat-1",
            thread_id="thread-1",
            text="@codex implement auth",
            sender_id="user-1",
        )
    )

    assert result.agent_id == "ag_polly"
    assert service.commands[0].source_event_id == "feishu:event-1"
    assert service.commands[0].input_text == "@codex implement auth"


def test_duplicate_feishu_event_creates_one_run_after_adapter_restart() -> None:
    deduper = SqlAlchemyLarkStore(database_url())
    service = FakeRunService()
    first = LarkAdapter(router=bound_router(service), deduper=deduper)
    second = LarkAdapter(router=bound_router(service), deduper=deduper)

    first.receive(message_payload(event_id="event-1"))
    replay = second.receive(message_payload(event_id="event-1"))

    assert replay.duplicate is True
    assert len(service.commands) == 1
```

- [ ] **Step 3: Run backend Feishu tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/server/test_feishu_routes.py tests/integrations/lark/test_adapter_router.py tests/integrations/lark/test_surface.py -q
```

Expected: FAIL because routes and `RunRequest` are Team-scoped and default persistence is a no-op.

- [ ] **Step 4: Implement durable Feishu installation/binding storage**

Create `omnigent/integrations/lark/store.py` with:

```python
@dataclass(frozen=True)
class AgentRouteBinding:
    installation_id: str
    agent_id: str
    chat_id: str
    thread_id: str | None
    default_workspace_id: str | None
    host_id: str | None
    execution_mode: str
    allowed_members: frozenset[str]


class LarkStore(Protocol):
    def save_installation(self, agent_id: str, credential: FeishuInstallationCredential, *, bot: Mapping[str, Any]) -> FeishuInstallationRecord: ...
    def get_for_agent(self, agent_id: str) -> FeishuInstallationRecord | None: ...
    def delete_for_agent(self, agent_id: str) -> bool: ...
    def resolve(self, chat_id: str, thread_id: str | None) -> AgentRouteBinding | None: ...
    def claim(self, scope: str, key: str, *, ttl: int) -> bool: ...
```

Implement it with `SqlFeishuInstallation`, `SqlFeishuThreadBinding`, and `SqlIdempotencyKey`. Persist only encrypted Secret bytes and non-secret Bot identity.

- [ ] **Step 5: Replace Team route context with Agent route context**

Change `omnigent/integrations/lark/router.py` to:

```python
@dataclass(frozen=True)
class FeishuRunRequest:
    text: str
    actor_id: str
    agent_id: str
    workspace_id: str | None
    chat_id: str
    thread_id: str | None
    event_id: str


class LarkRouter:
    def __init__(self, *, binding_store: LarkStore, run_service: RunService) -> None:
        self._bindings = binding_store
        self._runs = run_service

    def route_message(self, event: LarkMessage) -> CreatedRun:
        binding = self._require_binding(event.chat_id, event.thread_id)
        self._require_member(binding, event.sender_id)
        return self._runs.create_sync(
            RunCreateCommand(
                agent_id=binding.agent_id,
                workspace_id=binding.default_workspace_id,
                source="feishu",
                source_event_id=f"feishu:{event.event_id}",
                input_text=event.text,
                actor_id=event.sender_id,
                host_id=binding.host_id,
                execution_mode=binding.execution_mode,
            )
        )
```

Card actions validate Agent ID, Run ID, Workspace binding, member, signed action, nonce, and state transition before calling a fixed allow-list service. They never accept arbitrary commands or callback URLs.

- [ ] **Step 6: Add Agent-scoped Feishu routes**

Implement these exact paths in `server/routes/feishu.py`:

```text
POST   /agents/{agent_id}/feishu/installations
GET    /agents/{agent_id}/feishu/installations/{session}
GET    /agents/{agent_id}/feishu
DELETE /agents/{agent_id}/feishu
POST   /agents/{agent_id}/feishu/surface/reinitialize
POST   /feishu/webhook
```

Device session state records `agent_id` at begin. Poll rejects a different path Agent. Successful poll persists the encrypted credential and calls the idempotent Surface provisioner. DELETE revokes the installation and bindings but does not delete the Agent, Runs, or Sessions.

- [ ] **Step 7: Update the web Feishu client**

Change all install functions to require `agentId`:

```typescript
export async function beginFeishuInstall(agentId: string): Promise<FeishuInstallSession> {
  return fetchJson(`/v1/agents/${encodeURIComponent(agentId)}/feishu/installations`, {
    method: "POST",
  });
}

export async function pollFeishuInstall(
  agentId: string,
  session: string,
): Promise<FeishuInstallStatus> {
  return fetchJson(
    `/v1/agents/${encodeURIComponent(agentId)}/feishu/installations/${encodeURIComponent(session)}`,
  );
}
```

Keep the QR visible while status is `pending`; use the provider's returned interval and cancel polling when the component unmounts or Agent ID changes.

- [ ] **Step 8: Run backend and frontend Feishu tests**

Run:

```bash
.venv/bin/pytest tests/server/test_feishu_routes.py tests/integrations/lark/test_adapter_router.py tests/integrations/lark/test_surface.py -q
pnpm --dir web test --run src/hooks/useFeishuInstall.test.tsx
```

Expected: PASS; restart idempotency and Agent mismatch are covered.

- [ ] **Step 9: Commit**

```bash
git add omnigent/integrations/lark omnigent/server/routes/feishu.py omnigent/server/app.py tests/server/test_feishu_routes.py tests/integrations/lark web/src/lib/feishuApi.ts web/src/hooks/useFeishuInstall.ts web/src/hooks/useFeishuInstall.test.tsx
git commit -m "feat(feishu): bind installations and runs to agents"
```

---

### Task 9: Make legacy Team APIs read-only and remove Team execution wiring

**Files:**

- Modify: `omnigent/server/routes/teams.py`
- Modify: `omnigent/server/app.py`
- Modify: `omnigent/server/schemas.py`
- Modify: `tests/server/test_team_routes.py`
- Modify: `web/src/App.tsx`
- Modify: `web/src/shell/Sidebar.tsx`
- Modify: `web/src/shell/Sidebar.test.tsx`

- [ ] **Step 1: Write failing compatibility tests**

Replace Team write expectations in `tests/server/test_team_routes.py` with:

```python
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/teams", {"name": "Legacy", "members": []}),
        ("PATCH", f"/v1/teams/{'1' * 32}", {"name": "Changed"}),
    ],
)
async def test_legacy_team_writes_return_migration_diagnostic(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: dict[str, object],
) -> None:
    response = await client.request(method, path, json=body)

    assert response.status_code == 410
    assert response.json() == {
        "error": {
            "code": "legacy_team_deprecated",
            "message": "Team configuration is read-only; create or clone a Multi-Agent Bundle.",
            "replacement": "/v1/agents",
        }
    }


async def test_legacy_unbound_team_read_reports_reconnect_required(
    client: httpx.AsyncClient,
) -> None:
    team_id = seed_legacy_unbound_team(client)

    response = await client.get(f"/v1/teams/{team_id}")

    assert response.status_code == 200
    assert response.json()["deprecated"] is True
    assert response.json()["migration_status"] == "legacy_unbound"
    assert response.json()["executable"] is False
```

Add a route table assertion proving `/v1/runs/{run_id}` belongs only to the new Run router.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/server/test_team_routes.py tests/server/test_app.py -q
```

Expected: FAIL because Team writes currently mutate the legacy store.

- [ ] **Step 3: Return `410 Gone` for legacy writes**

Keep GET `/teams` and GET `/teams/{id}` as diagnostic reads. Replace POST/PATCH handlers with a shared response:

```python
def _legacy_team_gone() -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content={
            "error": {
                "code": "legacy_team_deprecated",
                "message": "Team configuration is read-only; create or clone a Multi-Agent Bundle.",
                "replacement": "/v1/agents",
            }
        },
    )
```

Remove `TeamMemoryStore.create_run`, `select_run_workspace`, and `/teams/{team_id}/runs` from production routing. Legacy Run rows are returned through the new RunStore with `legacy_state` and no fabricated Session details.

Add a deprecation comment naming the planned removal release according to `AGENTS.md`; use the product's next agreed minor release identifier consistently in code and the eventual PR description.

- [ ] **Step 4: Remove old Coordinator/Scheduler construction from app wiring**

Search and remove every production import or construction of:

```text
Coordinator
DAGScheduler
ParentInbox
CoordinatorRouter
AgentProfile
```

from `server/app.py`, Feishu wiring, and Run routes. Tests may still import the legacy modules for compatibility coverage.

- [ ] **Step 5: Remove Team navigation and routes**

In `web/src/App.tsx`, remove:

```tsx
<Route path={`${prefix}/teams`} element={<TeamsPage />} />
<Route path={`${prefix}/teams/new`} element={<TeamDetailPage />} />
<Route path={`${prefix}/teams/:teamId`} element={<TeamDetailPage />} />
```

Keep `/runs/:runId`, but classify it with Multi-Agent navigation. In `Sidebar.tsx`, remove `teams-nav` and its Teams link. Update `Sidebar.test.tsx` to assert the Multi-Agent entry exists and Teams does not.

- [ ] **Step 6: Run backend and navigation tests**

Run:

```bash
.venv/bin/pytest tests/server/test_team_routes.py tests/server/test_app.py -q
pnpm --dir web test --run src/shell/Sidebar.test.tsx
rg -n 'Coordinator\(|DAGScheduler\(|ParentInbox\(' omnigent/server omnigent/integrations/lark
```

Expected: all tests PASS and the search returns no production execution construction.

- [ ] **Step 7: Commit**

```bash
git add omnigent/server/routes/teams.py omnigent/server/app.py omnigent/server/schemas.py tests/server/test_team_routes.py web/src/App.tsx web/src/shell/Sidebar.tsx web/src/shell/Sidebar.test.tsx
git commit -m "refactor(teams): retire legacy execution writes"
```

---

### Task 10: Serve and render a Session-backed Run Inspector

**Files:**

- Modify: `omnigent/entities/run_projection.py`
- Modify: `omnigent/stores/run_store/sqlalchemy_store.py`
- Modify: `omnigent/server/routes/runs.py`
- Modify: `omnigent/server/schemas.py`
- Modify: `tests/stores/test_run_store.py`
- Modify: `tests/server/test_runs_routes.py`
- Create: `web/src/lib/runsApi.ts`
- Create: `web/src/hooks/useAgentRuns.ts`
- Modify: `web/src/components/runs/RunInspector.tsx`
- Create: `web/src/components/runs/RunInspector.test.tsx`
- Modify: `web/src/pages/RunInspectorPage.tsx`
- Modify: `web/src/pages/RunInspectorPage.test.tsx`

- [ ] **Step 1: Write failing Inspector API tests**

Add to `tests/server/test_runs_routes.py`:

```python
async def test_run_inspector_returns_session_references_not_transcript_copies(
    client: httpx.AsyncClient,
    projected_run: ProjectedRunFixture,
) -> None:
    response = await client.get(f"/v1/runs/{projected_run.run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == {
        "id": projected_run.agent_id,
        "bundle_version": 4,
        "bundle_digest": "a" * 64,
    }
    assert body["root_session_id"] == projected_run.root_session_id
    assert body["attempts"][0]["session_id"] == projected_run.child_session_id
    assert body["attempts"][0]["session_href"] == (
        f"/sessions/{projected_run.child_session_id}"
    )
    serialized = json.dumps(body)
    assert projected_run.full_worker_transcript not in serialized
```

Add assertions for Purpose, Harness, Model, start/end times, failure code, Worktree/repository records, explicit dependencies, artifact references, and ordered projection events.

- [ ] **Step 2: Write failing component tests**

Create `web/src/components/runs/RunInspector.test.tsx`:

```tsx
it("shows the pinned bundle and links each attempt to its Session", () => {
  render(<RunInspector run={fixtureRunInspector()} />);

  expect(screen.getByText("Version 4")).toBeInTheDocument();
  expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /codex.*auth-refactor/i })).toHaveAttribute(
    "href",
    "/sessions/child-1",
  );
  expect(screen.getByText("implement")).toBeInTheDocument();
  expect(screen.getByText("codex-native")).toBeInTheDocument();
  expect(screen.queryByText("agent profile")).not.toBeInTheDocument();
});


it("renders legacy unbound runs as non-executable diagnostics", () => {
  render(<RunInspector run={fixtureLegacyRun()} />);

  expect(screen.getByText(/legacy run is not bound to an agent bundle/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /retry|run/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run API and UI tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/stores/test_run_store.py tests/server/test_runs_routes.py -q
pnpm --dir web test --run src/components/runs/RunInspector.test.tsx src/pages/RunInspectorPage.test.tsx
```

Expected: FAIL because the API returns only the basic legacy Run shape and the component still labels Team/Profile fields.

- [ ] **Step 4: Define explicit Inspector response schemas**

Add Pydantic response models:

```python
class RunAgentRef(BaseModel):
    id: str | None
    bundle_version: int | None
    bundle_digest: str | None


class RunAttemptResponse(BaseModel):
    id: str
    task_id: str
    session_id: str | None
    session_href: str | None
    worker_name: str | None
    worker_config_path: str | None
    purpose: str | None
    harness: str | None
    model: str | None
    status: str
    started_at: int | None
    completed_at: int | None
    failure_code: str | None


class RunInspectorResponse(BaseModel):
    id: str
    status: str
    legacy_state: str
    source: str
    agent: RunAgentRef
    workspace_id: str | None
    root_session_id: str | None
    root_session_href: str | None
    tasks: list[RunTaskResponse]
    attempts: list[RunAttemptResponse]
    events: list[RunEventResponse]
    artifacts: list[RunArtifactResponse]
    repositories: list[RunRepositoryResponse]
```

Do not add `[key: string]: unknown` or raw ORM payloads to the response.

- [ ] **Step 5: Build Inspector data from references**

In `SqlAlchemyRunStore.get_inspector`:

- query Run, Tasks, Dependencies, Attempts, Events, Artifacts, and Worktree Leases in bounded batched queries;
- sort events by durable sequence and Attempts by `started_at, id`;
- compute overlap/parallel timing from Attempt timestamps without copying output;
- build Session links as `/sessions/{session_id}`;
- include `conversation_item_id` as a reference when available;
- expose projection failure diagnostics while leaving underlying Session state authoritative;
- return legacy rows with empty Session-backed collections and `legacy_state` unchanged.

- [ ] **Step 6: Replace the open frontend API shape**

Create `web/src/lib/runsApi.ts` with explicit types matching the Pydantic response and functions:

```typescript
export async function listAgentRuns(agentId: string): Promise<RunSummary[]>;
export async function getRunInspector(runId: string): Promise<RunInspectorRecord>;
export async function createRun(input: CreateRunInput): Promise<RunSummary>;
```

Parse network responses with the web package's existing schema/fallback convention. Do not cast arbitrary JSON to `RunInspectorRecord`.

Create `useAgentRuns.ts` with query keys:

```typescript
export const agentRunsQueryKey = (agentId: string) => ["agents", agentId, "runs"] as const;
export const runInspectorQueryKey = (runId: string) => ["runs", runId, "inspector"] as const;
```

Refetch only while Run status is non-terminal.

- [ ] **Step 7: Update Inspector rendering and navigation**

In `RunInspector.tsx`:

- remove open-object fallback helpers for primary fields;
- render Agent ID, Version, full Digest with copy affordance, Workspace, source, and root Session;
- render Worker, Purpose, Harness, Model, and child Session link per Attempt;
- render explicit dependencies only;
- render actual parallel overlap from timestamps;
- display Worktree/Commit/Test/Artifact references;
- display a clear read-only `legacy_unbound` diagnostic;
- never render copied stdout/stderr unless the API returns a bounded artifact/log reference.

In `RunInspectorPage.tsx`, link back to `/multi-agent/{agent_id}` when bound and `/multi-agent` when legacy/unbound.

- [ ] **Step 8: Run API and frontend tests**

Run:

```bash
.venv/bin/pytest tests/stores/test_run_store.py tests/server/test_runs_routes.py -q
pnpm --dir web test --run src/components/runs/RunInspector.test.tsx src/pages/RunInspectorPage.test.tsx
pnpm --dir web type-check
```

Expected: PASS with no Team/Profile labels in the Inspector.

- [ ] **Step 9: Commit**

```bash
git add omnigent/entities/run_projection.py omnigent/stores/run_store/sqlalchemy_store.py omnigent/server/routes/runs.py omnigent/server/schemas.py tests/stores/test_run_store.py tests/server/test_runs_routes.py web/src/lib/runsApi.ts web/src/hooks/useAgentRuns.ts web/src/components/runs/RunInspector.tsx web/src/components/runs/RunInspector.test.tsx web/src/pages/RunInspectorPage.tsx web/src/pages/RunInspectorPage.test.tsx
git commit -m "feat(runs): serve session-backed run inspector"
```

---

### Task 11: Prove Bundle pinning, parallel Worker Sessions, auto-wake, Feishu routing, and multi-repository isolation end to end

**Files:**

- Modify: `tests/e2e/test_subagent_autowake_e2e.py`
- Replace: `tests/e2e/test_feishu_team_harness.py`
- Modify: `tests/teams/test_multirepo_worktree_lease.py`
- Modify: `docs/feishu-team-harness-runbook.md`

- [ ] **Step 1: Replace the fake Team acceptance with a real Session-backed E2E**

Rewrite `tests/e2e/test_feishu_team_harness.py` so it uses a real FastAPI app, real SQL stores, fake Lark transport, fake Harness executable, and fake Host transport. It must not define `HarnessCoordinator`, `AcceptedRun`, `FakeHost.run_workers`, or an in-memory Run dictionary.

The primary E2E must perform:

```python
def test_feishu_agent_run_projects_parallel_workers_and_auto_review(
    live_server: str,
    fake_lark: FakeLarkTransport,
    fake_harness: ParallelSubagentHarness,
) -> None:
    agent = clone_polly_template(live_server, name="研发小队")
    bind_feishu_agent(live_server, agent["id"], fake_lark)
    workspace = register_multi_repo_workspace(live_server, repositories=("api", "core"))
    select_feishu_workspace(fake_lark, agent["id"], workspace["id"])

    accepted = fake_lark.emit_text(
        event_id="message-1",
        text="实现认证并由独立 Worker 审查",
    )
    run = wait_for_run_terminal(live_server, accepted.run_id)
    inspector = get_run_inspector(live_server, run["id"])

    implement_attempts = [a for a in inspector["attempts"] if a["purpose"] == "implement"]
    review_attempts = [a for a in inspector["attempts"] if a["purpose"] == "review"]
    assert len(implement_attempts) == 2
    assert intervals_overlap(implement_attempts[0], implement_attempts[1])
    assert implement_attempts[0]["worker_name"] == implement_attempts[1]["worker_name"]
    assert implement_attempts[0]["session_id"] != implement_attempts[1]["session_id"]
    assert review_attempts
    assert review_attempts[0]["worker_name"] != implement_attempts[0]["worker_name"]
    assert fake_harness.user_message_count == 1
    assert run["status"] == "completed"
```

The fake Harness must emit two `sys_session_send` calls in the same Coordinator response with the same Worker and distinct titles, complete both asynchronously, accept the automatic Coordinator continuation, then emit a Review dispatch to a different Worker. Timing assertions use recorded start/end events, not sleeps as proof.

- [ ] **Step 2: Add Bundle update pinning to the E2E**

Add:

```python
def test_running_and_resumed_run_keep_old_digest_after_agent_update(live_server: str) -> None:
    agent = create_versioned_multi_agent(live_server, marker="version-one")
    first = create_run(live_server, agent["id"], input="start and pause before child")
    first_snapshot = get_run(live_server, first["id"])

    update_agent_bundle(live_server, agent["id"], marker="version-two")
    resume_root_session(live_server, first_snapshot["root_session_id"])
    first_finished = wait_for_run_terminal(live_server, first["id"])
    second = create_run(live_server, agent["id"], input="new run")

    assert first_finished["bundle_digest"] == first_snapshot["bundle_digest"]
    assert child_markers(first_finished) == {"version-one"}
    assert get_run(live_server, second["id"])["bundle_digest"] != first_snapshot["bundle_digest"]
    assert child_markers(get_run(live_server, second["id"])) == {"version-two"}
```

- [ ] **Step 3: Add failure/autowake and workspace immutability cases**

Cover these assertions in the same E2E module:

```text
Worker boot failure creates a failed Attempt with failure_code and wakes Coordinator.
Coordinator chooses another Worker after the failure without a second user message.
Duplicate Feishu event after app restart returns the original Run.
Worker-name mention still produces a root Coordinator Session.
Workspace selection change during a running Run affects only the next Run.
Each writable repository has a different worktree path per concurrent Child Session.
Original sibling repositories remain unchanged.
Feishu notification failure records delivery failure but Run still reaches its true terminal state.
```

- [ ] **Step 4: Run the real E2E and verify RED before final fixes**

Run:

```bash
.venv/bin/pytest tests/e2e/test_subagent_autowake_e2e.py tests/e2e/test_feishu_team_harness.py -q
```

Expected on first run: at least one assertion fails at the first unconnected real lifecycle boundary. Fix only the failing production seam; do not restore fake Coordinator logic or add timing-only assertions.

- [ ] **Step 5: Run the E2E until GREEN**

Run:

```bash
.venv/bin/pytest tests/e2e/test_subagent_autowake_e2e.py tests/e2e/test_feishu_team_harness.py -q --count=1
```

Expected: PASS with one user input, overlapping Worker Attempt intervals, an automatic Coordinator continuation, and an independent Review Attempt.

- [ ] **Step 6: Update the runbook to match Agent-scoped behavior**

Update `docs/feishu-team-harness-runbook.md` so its exact acceptance flow is:

```text
Clone a built-in Multi-Agent Bundle.
Connect Feishu from the cloned Agent.
Register/select a multi-repository Workspace.
Send one Feishu task.
Open the Run Inspector.
Verify Agent ID, Bundle Version/Digest, root Session, overlapping Worker Sessions,
automatic Coordinator continuation, Review Attempt, worktrees, tests, artifacts, and final notification.
```

Remove instructions to create Team Members, configure AgentProfile concurrency, or manually comment to advance Review.

- [ ] **Step 7: Commit**

```bash
git add tests/e2e/test_subagent_autowake_e2e.py tests/e2e/test_feishu_team_harness.py tests/teams/test_multirepo_worktree_lease.py docs/feishu-team-harness-runbook.md
git commit -m "test(e2e): verify agent-scoped session runtime"
```

---

### Task 12: Run migration, backend, frontend, source, and browser completion gates

**Files:**

- Verify: all files changed in Tasks 1–11
- Modify only if a gate identifies a defect directly caused by this implementation

- [ ] **Step 1: Run the migration and model gates**

Run:

```bash
.venv/bin/pytest tests/db/test_team_harness_migration.py tests/db/test_migrations_sqlite_safe.py tests/stores/test_agent_store.py tests/stores/test_conversation_store.py tests/stores/test_conversation_store_split_db.py tests/stores/test_run_store.py -q
.venv/bin/alembic -c omnigent/db/alembic.ini heads
```

Expected: all tests PASS and one migration head.

- [ ] **Step 2: Run runtime, Session, Workspace, and Feishu backend gates**

Run:

```bash
.venv/bin/pytest tests/runtime/test_agent_cache.py tests/server/test_runner_session_init.py tests/server/test_runs_routes.py tests/server/test_feishu_routes.py tests/server/test_team_routes.py tests/server/integration/test_run_projection.py tests/teams/test_workspace_registry.py tests/teams/test_multirepo_worktree_lease.py tests/integrations/lark -q
```

Expected: PASS.

- [ ] **Step 3: Run the real Session E2E gates**

Run:

```bash
.venv/bin/pytest tests/e2e/test_subagent_autowake_e2e.py tests/e2e/test_feishu_team_harness.py -q --count=1
```

Expected: PASS.

- [ ] **Step 4: Run frontend tests and type checking**

Run:

```bash
pnpm --dir web test --run src/hooks/useFeishuInstall.test.tsx src/components/runs/RunInspector.test.tsx src/pages/RunInspectorPage.test.tsx src/shell/Sidebar.test.tsx
pnpm --dir web type-check
```

Expected: PASS.

- [ ] **Step 5: Run source audits for forbidden dual-engine wiring**

Run:

```bash
rg -n 'Coordinator\(|DAGScheduler\(|ParentInbox\(' omnigent/server omnigent/integrations/lark omnigent/runs
rg -n 'team_id|coordinator_id|agent_profile_id|concurrency' omnigent/integrations/lark omnigent/runs web/src/components/runs web/src/lib/runsApi.ts
rg -n '/v1/teams|teams-nav|/teams/' web/src/App.tsx web/src/shell/Sidebar.tsx web/src/components/runs web/src/lib/runsApi.ts
```

Expected:

- first command returns no production runtime matches;
- second command returns only explicit legacy migration/response compatibility fields, never routing identity;
- third command returns no active navigation or Run client usage.

- [ ] **Step 6: Run repository verification**

Run:

```bash
just lint
.venv/bin/pytest -q
pnpm --dir web test --run
pnpm --dir web type-check
```

Expected: all configured non-E2E backend tests, web tests, lint, and type checks PASS.

- [ ] **Step 7: Perform the required browser acceptance**

Start the local server using the repository's documented development command, then verify in the real browser:

1. Multi-Agent cards show built-in and cloned Agent Bundles, not Team rows.
2. A cloned Agent can connect Feishu and retain the QR while pending.
3. A multi-repository Workspace can be selected for a new Run.
4. Creating one task opens one root Coordinator Session.
5. Inspector shows the exact Bundle Version/Digest and immutable Workspace.
6. Two same-Worker/different-title Attempts visibly overlap.
7. Coordinator continues after Worker completion without a second message.
8. A different Worker performs Review.
9. Each Attempt links to the existing Session detail.
10. Legacy unbound Run data is read-only and shows a reconnect diagnostic.
11. English and Simplified Chinese both render the changed Run/Feishu surfaces without clearing state.

Expected: every item succeeds against the running application; screenshots or a short recording are attached to the eventual PR.

- [ ] **Step 8: Commit gate fixes, if any**

If verification required directly related corrections, commit them atomically:

```bash
git add <only-files-corrected-by-the-gates>
git commit -m "fix(runtime): satisfy multi-agent acceptance gates"
```

If no corrections were necessary, skip this commit.

---

## Final acceptance checklist

- [ ] Root and Child Sessions share the same immutable Agent Bundle snapshot.
- [ ] Updating an Agent cannot change an already-started or resumed Run.
- [ ] AgentCache holds two versions of one Agent without collision.
- [ ] RunStore only projects real Session/Conversation events.
- [ ] No production path constructs the legacy Coordinator or DAG Scheduler.
- [ ] Same Worker plus different titles creates concurrent Child Sessions and Attempts.
- [ ] Same Worker plus same title/new turn creates a new Attempt on the existing Child Session.
- [ ] Worker completion/failure uses the existing Parent Inbox and auto-wake path.
- [ ] Feishu is bound to Agent ID and enters only the root Coordinator.
- [ ] Duplicate Feishu events remain idempotent after process restart.
- [ ] Workspace changes affect only new Runs.
- [ ] Multi-repository writable work is isolated by durable Attempt/Session leases.
- [ ] Legacy Team writes return `410 Gone`; legacy reads remain diagnosable.
- [ ] Inspector displays Version/Digest, Session tree, Purpose, Harness, Model, timing, Worktrees, artifacts, and failures without copying transcripts.
- [ ] Migration, backend, frontend, real E2E, source audit, and browser acceptance gates pass.
