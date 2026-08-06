# Standalone Feishu Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all Feishu/Lark provider behavior into a standalone `omnigent-feishu` package under `integrations/feishu`, bind it to durable Agent Bundles rather than Teams, and drive the provider-neutral Omnigent Run API without duplicating Run, Session, Workspace, or execution state.

**Architecture:** `omnigent-feishu` owns Feishu registration, credentials, events, cards, surfaces, provider bindings, delivery retries, and provider-local idempotency. Omnigent core remains authoritative for Agent Bundles, Bundle snapshots, Run/Task/Attempt, Session trees, Workspace definitions, worktree leases, logs, evaluation, and authentication. The only execution dependency points from the external integration to authenticated Omnigent HTTP APIs; core production modules never import Feishu implementation modules.

**Tech Stack:** Python 3.12+, FastAPI, httpx, aiosqlite, cryptography, Pydantic v2, existing Omnigent device grant/auth APIs, pytest/pytest-asyncio, React 19, TanStack Query, Vitest.

---

## Invariants

1. `omnigent_feishu -> authenticated Omnigent HTTP API -> Run/Session runtime` is the only execution dependency direction.
2. Core production code imports neither `omnigent_feishu` nor `omnigent.integrations.lark`.
3. Feishu installations and bindings reference `agent_id`, `workspace_id`, and `run_id`; they never reference Team, Coordinator profile, or AgentProfile.
4. Feishu never writes Run, Task, Attempt, Session transcript, Bundle content, or Workspace repository definitions into its provider database.
5. `POST /v1/runs` is the only Run creation boundary; Feishu does not hold a `RunService` object.
6. Feishu sender IDs are provider metadata, not core actor IDs. Core actor identity comes from the authenticated bearer.
7. External event idempotency and core Run idempotency are both required: they protect different retry boundaries.
8. Historical Alembic revisions and legacy Feishu tables remain intact and read-only; migration is a repeatable one-time import, never long-term dual write.
9. Feishu delivery failure is observable but never changes the authoritative Run terminal state.
10. The old embedded adapter is removed only after the standalone package, CLI, import, webhook cutover, WebUI cutover, and cross-process E2E all pass.

## File map

### New standalone package

- `integrations/feishu/pyproject.toml`: independent package metadata and provider-only dependencies.
- `integrations/feishu/src/omnigent_feishu/__main__.py`: `python -m omnigent_feishu` entry point.
- `integrations/feishu/src/omnigent_feishu/app.py`: standalone FastAPI assembly and lifecycle.
- `integrations/feishu/src/omnigent_feishu/config.py`: environment-backed configuration.
- `integrations/feishu/src/omnigent_feishu/models.py`: installation, binding, event, notification, and surface records.
- `integrations/feishu/src/omnigent_feishu/protocol.py`: Feishu envelope parsing and signature verification.
- `integrations/feishu/src/omnigent_feishu/credentials.py`: encrypted provider credentials and delegated bearer values.
- `integrations/feishu/src/omnigent_feishu/device_flow.py`: PersonalAgent QR registration.
- `integrations/feishu/src/omnigent_feishu/cards.py`: messages, cards, actions, and persistent workspace UI.
- `integrations/feishu/src/omnigent_feishu/surface.py`: idempotent menu/card provisioning.
- `integrations/feishu/src/omnigent_feishu/store.py`: provider SQLite schema and transactions.
- `integrations/feishu/src/omnigent_feishu/core_client.py`: narrow authenticated Agent/Workspace/Run/Event client.
- `integrations/feishu/src/omnigent_feishu/auth.py`: delegated/service credential acquisition and refresh.
- `integrations/feishu/src/omnigent_feishu/router.py`: chat/thread binding to Agent-scoped Run requests.
- `integrations/feishu/src/omnigent_feishu/adapter.py`: deduplication, dispatch, retry, and notification orchestration.
- `integrations/feishu/src/omnigent_feishu/routes.py`: health, install, binding, surface, action, and webhook endpoints.
- `integrations/feishu/src/omnigent_feishu/legacy_import.py`: idempotent import from legacy core tables.
- `integrations/feishu/tests/*`: provider unit and integration tests with fake provider transport and fake core HTTP service.

### Core files retained or modified

- `omnigent/runs/service.py`, `omnigent/server/routes/runs.py`: provider-neutral authenticated Run creation.
- `omnigent/server/schemas.py`: namespaced integration source and idempotency metadata.
- `omnigent/cli.py`, `omnigent/integration_daemon.py`: generic integration process lifecycle.
- `pyproject.toml`, `uv.lock`: `feishu` optional dependency and editable workspace source.
- `scripts/update_versions.py`, `tests/scripts/test_update_versions.py`: lockstep package versioning.
- `web/src/lib/feishuApi.ts`, `web/src/hooks/useFeishuInstall.ts`: Agent-scoped external/forwarded API calls.
- `web/src/components/multi-agents/FeishuPairingPanel.tsx`: Multi-Agent connection UI.
- `omnigent/server/app.py`, `omnigent/server/routes/feishu.py`: temporary proxy followed by removal of embedded provider lifecycle.

### Historical compatibility only

- `omnigent/db/migrations/versions/za1b2c3d4e5f_add_team_harness_tables.py`: never edit or rename.
- `SqlFeishuInstallation`, `SqlFeishuNotification`: read-only legacy import source until one removal cycle has elapsed.

### Removed after cutover

- `omnigent/integrations/lark/*`
- embedded `omnigent/server/routes/feishu.py`
- `create_app(..., lark_adapter=...)` and all embedded adapter lifecycle wiring
- Team-scoped Feishu aliases and WebUI entry points

### Task 1: Make the core Run API provider-neutral and externally idempotent

**Files:**
- Modify: `omnigent/runs/service.py`
- Modify: `omnigent/server/routes/runs.py`
- Modify: `omnigent/server/schemas.py`
- Modify: `tests/runs/test_service.py`
- Modify: `tests/server/test_runs_routes.py`

- [ ] **Step 1: Write failing external-client contract tests**

```python
def test_integration_source_event_is_idempotent(run_client, agent_id, workspace_id):
    body = {
        "agent_id": agent_id,
        "workspace_id": workspace_id,
        "input": "implement auth and review it",
        "source": "integration:feishu",
        "source_event_id": "feishu:event-1",
    }
    first = run_client.post("/v1/runs", json=body)
    second = run_client.post("/v1/runs", json=body)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_run_actor_comes_from_bearer_not_source_metadata(authenticated_run_client):
    response = authenticated_run_client.post(
        "/v1/runs",
        json={
            "agent_id": "ag_test",
            "workspace_id": "ws_test",
            "input": "inspect",
            "source": "integration:feishu",
            "source_event_id": "feishu:event-2",
            "source_actor": "ou_provider_sender",
        },
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest tests/runs/test_service.py tests/server/test_runs_routes.py -q`

Expected: FAIL because the current request schema uses a provider-specific source literal or lacks `(source, source_event_id)` idempotency.

- [ ] **Step 3: Implement the exact neutral command contract**

```python
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    workspace_id: str | None = None
    input: str = Field(min_length=1, max_length=200_000)
    source: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*(?::[a-z0-9_-]+)?$", max_length=64)]
    source_event_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    host_id: str | None = None
    execution_mode: Literal["auto", "cautious", "read_only"] = "auto"
```

Derive `actor_id` exclusively from the authenticated request context. Persist and atomically reuse the Run keyed by `(authenticated tenant/workspace scope, source, source_event_id)`; the selected Run `workspace_id` is data, not part of that idempotency identity, so retrying one provider event with a changed payload cannot create a second Run. Do not import Feishu types or accept Team/Profile identifiers.

- [ ] **Step 4: Verify GREEN and source audit**

Run:

```bash
.venv/bin/pytest tests/runs/test_service.py tests/server/test_runs_routes.py -q
rg -n 'Feishu|Lark|TeamStore|AgentProfile|DAGScheduler' omnigent/runs omnigent/server/routes/runs.py
```

Expected: tests PASS; source audit has no provider or legacy execution dependency.

- [ ] **Step 5: Commit**

```bash
git add omnigent/runs/service.py omnigent/server/routes/runs.py omnigent/server/schemas.py tests/runs/test_service.py tests/server/test_runs_routes.py
git commit -m "feat(runs): expose provider-neutral idempotent run creation"
```

### Task 2: Scaffold the independent Feishu package and version lifecycle

**Files:**
- Create: `integrations/feishu/pyproject.toml`
- Create: `integrations/feishu/src/omnigent_feishu/__init__.py`
- Create: `integrations/feishu/src/omnigent_feishu/__main__.py`
- Create: `integrations/feishu/src/omnigent_feishu/config.py`
- Create: `integrations/feishu/tests/test_config.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `scripts/update_versions.py`
- Modify: `tests/scripts/test_update_versions.py`

- [ ] **Step 1: Write failing package and version tests**

```python
import subprocess
import sys

import pytest
from pydantic import ValidationError


def test_feishu_config_requires_server_and_encryption_key(monkeypatch):
    monkeypatch.delenv("OMNIGENT_SERVER_URL", raising=False)
    monkeypatch.delenv("OMNIGENT_FEISHU_CREDENTIAL_KEY", raising=False)
    with pytest.raises(ValidationError):
        FeishuConfig()


def test_module_help_is_available():
    result = subprocess.run(
        [sys.executable, "-m", "omnigent_feishu", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
```

Extend `tests/scripts/test_update_versions.py` so the package list contains `integrations/feishu/pyproject.toml` and all five Python package versions remain equal.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest integrations/feishu/tests/test_config.py tests/scripts/test_update_versions.py -q`

Expected: FAIL because the package does not exist.

- [ ] **Step 3: Add the minimal package**

Use this dependency boundary in `integrations/feishu/pyproject.toml`:

```toml
[project]
name = "omnigent-feishu"
version = "0.8.0.dev0"
requires-python = ">=3.12"
dependencies = [
  "aiohttp>=3.12.0",
  "aiosqlite>=0.21.0",
  "cryptography>=42.0.0",
  "fastapi>=0.115.0",
  "httpx>=0.28.0",
  "pydantic-settings>=2.10.0",
  "uvicorn>=0.34.0",
]
```

Add root `feishu = ["omnigent-feishu==0.8.0.dev0"]` and an editable workspace source, mirroring Slack. `__main__.py` may only import the standalone package and must not import core ORM/runtime implementation.

- [ ] **Step 4: Lock and verify**

Run:

```bash
uv lock
uv sync --extra feishu --extra dev
.venv/bin/pytest integrations/feishu/tests/test_config.py tests/scripts/test_update_versions.py -q
.venv/bin/python scripts/update_versions.py check
```

Expected: all commands PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/feishu pyproject.toml uv.lock scripts/update_versions.py tests/scripts/test_update_versions.py
git commit -m "feat(feishu): add standalone integration package"
```

### Task 3: Move pure provider protocol, registration, credential, card, and surface behavior

**Files:**
- Create: `integrations/feishu/src/omnigent_feishu/{protocol,credentials,device_flow,cards,surface}.py`
- Create: `integrations/feishu/tests/{fakes,test_protocol,test_credentials,test_device_flow,test_cards,test_surface}.py`
- Read as migration source: `omnigent/integrations/lark/{protocol,credentials,device_flow,cards,surface}.py`

- [ ] **Step 1: Copy tests first and change imports**

Move provider-only behavior tests into the package and import from `omnigent_feishu`. Add an import-boundary assertion:

```python
def test_provider_modules_do_not_import_core_runtime():
    sources = "\n".join(path.read_text() for path in PROVIDER_SOURCE_PATHS)
    for forbidden in (
        "omnigent.db",
        "omnigent.runs",
        "omnigent.teams",
        "omnigent.stores",
        "omnigent.server.app",
    ):
        assert forbidden not in sources
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest integrations/feishu/tests/test_protocol.py integrations/feishu/tests/test_device_flow.py integrations/feishu/tests/test_surface.py -q`

Expected: FAIL on missing external modules.

- [ ] **Step 3: Move the minimal provider implementation**

Preserve verified behavior:

- QR registration uses `POST https://accounts.feishu.cn/oauth/v1/app/registration` as form data.
- `app_secret` is encrypted before persistence and absent from API responses/logs.
- event signature/verification failure is fail-closed.
- actions use signed payload, nonce, allowlisted operation, Agent/Workspace binding, member authorization, and idempotency.
- menu provisioning falls back to one persistent card with `partial` status; retries upsert the same surface identity.

Do not move SQLAlchemy models, RunService, Team routing, or core app construction.

- [ ] **Step 4: Verify provider tests**

Run: `.venv/bin/pytest integrations/feishu/tests/test_protocol.py integrations/feishu/tests/test_credentials.py integrations/feishu/tests/test_device_flow.py integrations/feishu/tests/test_cards.py integrations/feishu/tests/test_surface.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/feishu/src/omnigent_feishu integrations/feishu/tests
git commit -m "feat(feishu): isolate provider registration and surfaces"
```

### Task 4: Add the provider store, authenticated core client, and Agent-scoped router

**Files:**
- Create: `integrations/feishu/src/omnigent_feishu/models.py`
- Create: `integrations/feishu/src/omnigent_feishu/store.py`
- Create: `integrations/feishu/src/omnigent_feishu/auth.py`
- Create: `integrations/feishu/src/omnigent_feishu/core_client.py`
- Create: `integrations/feishu/src/omnigent_feishu/router.py`
- Create: `integrations/feishu/tests/test_store.py`
- Create: `integrations/feishu/tests/test_core_client.py`
- Create: `integrations/feishu/tests/test_router.py`

- [ ] **Step 1: Write failing persistence and routing tests**

```python
async def test_duplicate_provider_event_reuses_one_run(store, router, core_client):
    binding = await store.bind_thread(
        installation_id="fi_1",
        chat_id="chat_1",
        thread_id="thread_1",
        agent_id="ag_polly",
        workspace_id="ws_repo_set",
    )
    first = await router.route(event("evt_1", binding, "implement auth"))
    second = await router.route(event("evt_1", binding, "implement auth"))
    assert second.run_id == first.run_id
    assert core_client.create_run_calls == 1


async def test_runtime_store_has_no_team_or_transcript_columns(store):
    columns = await store.table_columns()
    forbidden = {"team_id", "coordinator_id", "agent_profile_id", "transcript", "bundle_yaml"}
    assert forbidden.isdisjoint(set().union(*columns.values()))
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest integrations/feishu/tests/test_store.py integrations/feishu/tests/test_core_client.py integrations/feishu/tests/test_router.py -q`

Expected: FAIL because the provider store and core client do not exist.

- [ ] **Step 3: Implement the exact provider schema and client**

Create provider tables `schema_meta`, `installations`, `thread_bindings`, `inbound_events`, `notifications`, `surfaces`, and `auth_grants`. Store only provider state plus core IDs. Use SQLite WAL and explicit transactions for event claim/completion.

`CoreClient.create_run()` must send:

```json
{
  "agent_id": "ag_polly",
  "workspace_id": "ws_repo_set",
  "input": "implement auth",
  "source": "integration:feishu",
  "source_event_id": "feishu:evt_1",
  "host_id": null,
  "execution_mode": "auto"
}
```

It must attach an Omnigent bearer, refresh once on 401, preserve structured 409/422 details, and never send Feishu `open_id` as core actor identity.

- [ ] **Step 4: Verify restart and retry behavior**

Run: `.venv/bin/pytest integrations/feishu/tests/test_store.py integrations/feishu/tests/test_core_client.py integrations/feishu/tests/test_router.py -q`

Expected: PASS, including reopening SQLite before processing the duplicate event.

- [ ] **Step 5: Commit**

```bash
git add integrations/feishu/src/omnigent_feishu integrations/feishu/tests
git commit -m "feat(feishu): route agent-bound events through the run API"
```

### Task 5: Serve the standalone integration and manage it through the generic CLI daemon

**Files:**
- Create: `integrations/feishu/src/omnigent_feishu/app.py`
- Create: `integrations/feishu/src/omnigent_feishu/routes.py`
- Create: `integrations/feishu/src/omnigent_feishu/adapter.py`
- Create: `integrations/feishu/tests/test_routes.py`
- Create: `integrations/feishu/tests/test_adapter.py`
- Modify: `omnigent/cli.py`
- Modify: `omnigent/integration_daemon.py`
- Create: `tests/cli/test_integration_feishu.py`

- [ ] **Step 1: Write failing route and CLI tests**

```python
def test_installation_routes_are_agent_scoped(client):
    response = client.post("/v1/agents/ag_polly/feishu/installations")
    assert response.status_code == 201
    assert response.json()["agent_id"] == "ag_polly"


def test_no_team_scoped_routes(client):
    assert client.post("/v1/teams/team_1/feishu/install/begin").status_code == 404


def test_feishu_background_lifecycle(cli_runner, fake_module):
    started = cli_runner.invoke(["integration", "feishu", "--background"])
    assert started.exit_code == 0
    assert cli_runner.invoke(["integration", "feishu", "status"]).exit_code == 0
    assert cli_runner.invoke(["integration", "feishu", "stop"]).exit_code == 0
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest integrations/feishu/tests/test_routes.py integrations/feishu/tests/test_adapter.py tests/cli/test_integration_feishu.py -q`

Expected: FAIL on missing app and CLI registration.

- [ ] **Step 3: Implement standalone routes and generic CLI registration**

Expose only:

```text
GET    /health
POST   /v1/agents/{agent_id}/feishu/installations
GET    /v1/agents/{agent_id}/feishu/installations/{session}
GET    /v1/agents/{agent_id}/feishu
DELETE /v1/agents/{agent_id}/feishu
GET    /v1/agents/{agent_id}/feishu/surface/status
POST   /v1/agents/{agent_id}/feishu/surface/reinitialize
POST   /v1/feishu/webhook
```

Extract a small `IntegrationCliSpec(name, module, install_hint)` from the Slack CLI lifecycle and register both Slack and Feishu. `IntegrationDaemon` stays provider-neutral and receives only the integration name, argv, environment, and state directory.

- [ ] **Step 4: Verify foreground/background/error behavior**

Run:

```bash
.venv/bin/pytest integrations/feishu/tests/test_routes.py integrations/feishu/tests/test_adapter.py tests/cli/test_integration_slack.py tests/cli/test_integration_feishu.py -q
```

Expected: PASS, including missing-package hint, immediate daemon failure log tail, reuse, status, stop, and logs.

- [ ] **Step 5: Commit**

```bash
git add integrations/feishu omnigent/cli.py omnigent/integration_daemon.py tests/cli/test_integration_feishu.py
git commit -m "feat(feishu): run the standalone integration daemon"
```

### Task 6: Import legacy installations once and cut provider traffic over without dual writes

**Files:**
- Create: `integrations/feishu/src/omnigent_feishu/legacy_import.py`
- Create: `integrations/feishu/tests/test_legacy_import.py`
- Modify: `omnigent/server/routes/feishu.py`
- Modify: `omnigent/server/app.py`
- Modify: `tests/server/test_feishu_routes.py`

- [ ] **Step 1: Write failing idempotent importer tests**

```python
async def test_legacy_import_is_repeatable(importer, legacy_db, provider_store):
    legacy_db.add_installation(team_id="team_1", app_id="cli_a")
    legacy_db.map_unique_coordinator("team_1", agent_id="ag_polly")
    first = await importer.run()
    second = await importer.run()
    assert first.imported == 1
    assert second.imported == 0
    assert await provider_store.installation_count() == 1


async def test_ambiguous_team_requires_reconnect(importer, legacy_db):
    legacy_db.map_coordinator_candidates("team_1", ["ag_a", "ag_b"])
    result = await importer.run()
    assert result.needs_reconnect == ["team_1"]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest integrations/feishu/tests/test_legacy_import.py tests/server/test_feishu_routes.py -q`

Expected: FAIL because the importer and proxy boundary do not exist.

- [ ] **Step 3: Implement stop-import-start cutover**

The importer may read legacy core tables but never write them. It imports only a unique durable Agent mapping, preserves encrypted credential bytes without logging them, records a `schema_meta` marker, and reports `needs_reconnect` for zero/multiple/session-scoped matches. Running it again is a no-op.

During one transition release, the core Agent-scoped Feishu route may be a thin HTTP proxy that forwards Authorization to the configured standalone service. It must not decrypt credentials, access provider tables, parse webhook payloads, or import `omnigent_feishu`. Webhooks point directly to the external service.

- [ ] **Step 4: Verify source and migration invariants**

Run:

```bash
.venv/bin/pytest integrations/feishu/tests/test_legacy_import.py tests/server/test_feishu_routes.py -q
.venv/bin/python -m omnigent_feishu.legacy_import --dry-run
.venv/bin/python -m omnigent_feishu.legacy_import
.venv/bin/python -m omnigent_feishu.legacy_import
```

Expected: second real import reports zero additions and zero modifications.

- [ ] **Step 5: Commit**

```bash
git add integrations/feishu/src/omnigent_feishu/legacy_import.py integrations/feishu/tests/test_legacy_import.py omnigent/server/routes/feishu.py omnigent/server/app.py tests/server/test_feishu_routes.py
git commit -m "feat(feishu): import legacy installations and proxy cutover"
```

### Task 7: Move pairing to Multi-Agent and remove the embedded production path

**Files:**
- Modify: `web/src/lib/feishuApi.ts`
- Modify: `web/src/hooks/useFeishuInstall.ts`
- Modify: `web/src/hooks/useFeishuInstall.test.tsx`
- Create: `web/src/components/multi-agents/FeishuPairingPanel.tsx`
- Modify: `web/src/pages/MultiAgentDetailPage.tsx`
- Modify: `web/src/pages/TeamDetailPage.tsx`
- Modify: `omnigent/server/app.py`
- Delete after compatibility gate: `omnigent/integrations/lark/*`
- Delete after compatibility gate: `omnigent/server/routes/feishu.py`

- [ ] **Step 1: Write failing Agent-scoped Web and source-audit tests**

```tsx
it("keeps simultaneous agent installation polls isolated", async () => {
  render(<><FeishuPairingPanel agentId="ag_a" /><FeishuPairingPanel agentId="ag_b" /></>);
  expect(queryClient.getQueryCache().find({ queryKey: ["feishu-install", "ag_a"] })).toBeTruthy();
  expect(queryClient.getQueryCache().find({ queryKey: ["feishu-install", "ag_b"] })).toBeTruthy();
});
```

Add a backend audit test that scans core production modules and fails on imports of `omnigent.integrations.lark` or `omnigent_feishu`, excluding the CLI's package-name string during the transition.

- [ ] **Step 2: Verify RED**

Run: `pnpm --dir web test -- src/hooks/useFeishuInstall.test.tsx && .venv/bin/pytest tests/server/test_feishu_decoupling.py -q`

Expected: FAIL on global installation query keys and embedded core imports.

- [ ] **Step 3: Cut WebUI and core lifecycle over**

Use query keys containing Agent identity and installation session:

```ts
["feishu-install", agentId, session]
```

Move the pairing panel under Multi-Agent cards/details and remove it from Team pages. Remove `create_app(..., lark_adapter=...)`, embedded start/close hooks, `app.state.lark_adapter`, default credential/device-flow construction, core provider store writes, and Team-scoped aliases. The core CLI may execute `python -m omnigent_feishu` by string but must never import the package.

- [ ] **Step 4: Verify no embedded production dependency**

Run:

```bash
pnpm --dir web test -- src/hooks/useFeishuInstall.test.tsx
.venv/bin/pytest tests/server/test_feishu_decoupling.py tests/cli/test_integration_feishu.py -q
rg -n 'omnigent\.integrations\.lark|create_feishu_router|lark_adapter' omnigent
rg -n 'team_id|coordinator_id|agent_profile_id' integrations/feishu/src/omnigent_feishu --glob '!legacy_import.py'
```

Expected: tests PASS; audits have no production match outside an explicitly expiring proxy allow-list.

- [ ] **Step 5: Commit**

```bash
git add web/src omnigent/server/app.py omnigent/server/routes omnigent/integrations tests/server/test_feishu_decoupling.py
git commit -m "refactor(feishu): cut over to the standalone agent integration"
```

### Task 8: Prove cross-process routing, restart idempotency, and browser behavior

**Files:**
- Create: `tests/e2e/test_feishu_agent_runtime_e2e.py`
- Modify: `tests/e2e/test_subagent_autowake_e2e.py`
- Verify: Multi-Agent/Feishu flow with the Codex in-app browser
- Modify: `docs/superpowers/plans/2026-08-04-multi-agent-feishu-runtime.md`

- [ ] **Step 1: Write failing cross-process E2E**

The E2E starts a real core app and a real standalone Feishu app with only provider network calls faked. It must assert:

```python
assert first_webhook.run_id == duplicate_after_feishu_restart.run_id
assert core.run(first_webhook.run_id).agent_id == "ag_polly"
assert core.run(first_webhook.run_id).bundle_digest == pinned_digest
assert core.run(first_webhook.run_id).workspace_id == "ws_multi_repo"
assert core.run(first_webhook.run_id).status == "completed"
assert feishu.notification(first_webhook.run_id).status in {"sent", "retrying"}
```

Add a notification-failure case that still requires the core Run to remain completed.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/e2e/test_feishu_agent_runtime_e2e.py -q`

Expected: FAIL until both process boundaries and cutover are complete.

- [ ] **Step 3: Complete browser acceptance with Codex**

Use the Codex in-app browser against the running local application; do not add a
Playwright spec solely for this acceptance step. Clone Polly, open its
Multi-Agent detail, start Agent-scoped QR pairing, retain the QR while pending,
show connected state (or the supported fixture-backed pending/error state when
external authorization is unavailable), switch the next Run's Workspace,
submit a task, inspect the root/worker Session tree, and verify a finished
product without navigating through any Team route. Repeat the visible flow in
English and Simplified Chinese without clearing application state. Record the
URL, observed bundle version/digest, immutable Workspace, root/worker Session
IDs, and screenshots as acceptance evidence.

- [ ] **Step 4: Run the complete gate**

```bash
uv sync --extra feishu --extra dev
.venv/bin/pytest integrations/feishu/tests tests/cli/test_integration_feishu.py tests/e2e/test_feishu_agent_runtime_e2e.py -q
.venv/bin/pytest tests/runs -q
.venv/bin/python scripts/update_versions.py check
# The web gates require Node >=22.13 (see package.json engines).
# If you use nvm and your shell defaults to an older release, select it first:
#   nvm use 22
pnpm --dir web test --run
pnpm --dir web type-check
pnpm --dir web build
just lint
```

Expected: every command PASS with no provider import in core and no Team-scoped runtime binding.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e docs/superpowers/plans/2026-08-04-standalone-feishu-integration.md docs/superpowers/plans/2026-08-04-multi-agent-feishu-runtime.md
git commit -m "test(feishu): prove standalone agent-scoped integration"
```

## Final acceptance checklist

- [ ] `python -m omnigent_feishu` starts independently.
- [ ] `omni integration feishu`, `--background`, `status`, `stop`, `logs`, and `logs -f` work.
- [ ] Core production code imports no Feishu/Lark implementation module.
- [ ] Feishu runtime source contains no Team/Coordinator/AgentProfile dependency outside `legacy_import.py`.
- [ ] Provider storage contains only provider state and core resource IDs.
- [ ] A duplicate webhook after external process restart returns the same Run.
- [ ] Feishu creates Runs only through authenticated `/v1/runs`.
- [ ] Run/Task/Attempt/Session/Workspace/log/evaluation authority remains in core.
- [ ] Feishu delivery failure does not change the Run terminal state.
- [ ] Legacy import is repeatable and performs no dual writes.
- [ ] Agent-scoped pairing and Workspace selection pass English and Simplified Chinese browser flows.
- [ ] No executable/mounted Team-scoped Feishu production path or embedded lifecycle remains; deprecated 410 wrappers and `/teams` redirects may remain as compatibility shells.
