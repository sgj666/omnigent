# Multi-Agent Integration and Browser Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that a persisted Polly-derived Multi-Agent can be configured, run concurrently, observed, connected to Feishu, localized, and operated end to end without manual continuation comments.

**Architecture:** Integration tests cross the Bundle API, durable stores, native root/child Session execution, Workspace leases, Run projections, Feishu adapter, and React application. Browser acceptance uses the same local server and persisted database as a user would use; mocks remain limited to external model and Feishu network boundaries where live credentials are unavailable.

**Tech Stack:** Pytest, FastAPI test client, Omnigent native runner, SQLite/PostgreSQL-compatible migrations, React/Vitest, Playwright E2E fixtures, pnpm/Vite, in-app browser.

---

## File map

- `tests/server/integration/test_multi_agent_bundle_lifecycle.py`: real Store/Artifact/Cache clone-edit-export lifecycle.
- `tests/e2e/test_multi_agent_native_execution_e2e.py`: native same-Worker concurrency, autowake and failure continuation.
- `tests/e2e/test_multi_agent_workspace_e2e.py`: multi-repository Workspace and worktree isolation.
- `tests/e2e/test_multi_agent_feishu_e2e.py`: Agent-scoped Device Flow, routing, surface and notifications.
- `tests/server/integration/test_run_projection.py`: durable Run/Task/Attempt/Session projection.
- `tests/e2e_ui/multi_agents/test_multi_agent_builder.py`: browser configuration and localization flow.
- `tests/e2e_ui/multi_agents/test_multi_agent_run.py`: browser Run and Inspector flow.
- `docs/superpowers/plans/2026-08-04-multi-agent-browser-acceptance.md`: checked manual acceptance record with observed IDs and outcomes.

### Task 1: Prove a real Polly Bundle survives clone, form patch and export

**Files:**
- Create: `tests/server/integration/test_multi_agent_bundle_lifecycle.py`
- Modify: `tests/server/test_agent_bundle_polly_roundtrip.py`

- [ ] **Step 1: Write the failing lifecycle test**

Create an app with real SQLAlchemy `AgentStore`, local `ArtifactStore`, and
`AgentCache`; obtain built-in Polly, clone it as `acceptance-polly`, remove the
Codex Worker model field, change the root description, export it, and assert:

```python
assert clone["builtin"] is False
assert clone["version"] == 1
assert saved["version"] == 2
assert exported.status_code == 200
assert validate_agent_bundle(exported.content).name == "acceptance-polly"
assert "skills/fanout/SKILL.md" in archive_paths(exported.content)
assert yaml_at(exported.content, "agents/codex/config.yaml", "executor", "model") is MISSING
```

- [ ] **Step 2: Run the test and verify the first unsupported HTTP operation fails**

Run: `.venv/bin/python -m pytest tests/server/integration/test_multi_agent_bundle_lifecycle.py -q`
Expected: FAIL on the missing clone, patch, or export contract rather than a fixture error.

- [ ] **Step 3: Complete only missing integration wiring**

Wire the existing Bundle service into `create_app`, use the production route
dependency graph, and fix no-op Cache/ArtifactStore test doubles that prevent
the real lifecycle. Do not duplicate Bundle parsing in the test.

- [ ] **Step 4: Run lifecycle and security regressions**

Run: `.venv/bin/python -m pytest tests/server/integration/test_multi_agent_bundle_lifecycle.py tests/server/test_agent_bundle_routes.py tests/server/test_agent_bundle_polly_roundtrip.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/server/integration/test_multi_agent_bundle_lifecycle.py tests/server/test_agent_bundle_polly_roundtrip.py omnigent/server/app.py
git commit -m "test: verify multi-agent bundle lifecycle"
```

### Task 2: Prove same-Worker parallel Sessions and automatic Coordinator continuation

**Files:**
- Create: `tests/e2e/test_multi_agent_native_execution_e2e.py`
- Modify: `tests/e2e/test_subagent_autowake_e2e.py`

- [ ] **Step 1: Write the failing native execution test**

Run a deterministic Polly-shaped Coordinator that emits two
`sys_session_send` calls in one response with the same Worker name and titles
`service-a` and `service-b`. The Worker fixture records monotonic start/end
times. Assert two distinct child Session IDs, overlapping execution intervals,
one root Session, and no second human message before the Coordinator's final
continuation.

- [ ] **Step 2: Add a failing Worker-start failure case**

Make `service-b` fail during startup and assert the parent receives a structured
completion/failure inbox event, the root receives a continuation turn, and the
Run projection records `failure_code` plus a final Coordinator result.

- [ ] **Step 3: Run both cases before implementation**

Run: `.venv/bin/python -m pytest tests/e2e/test_multi_agent_native_execution_e2e.py -q`
Expected: FAIL because native lifecycle events are not yet projected or the fixture cannot inspect the child timing.

- [ ] **Step 4: Add the smallest observability seam**

Reuse `(agent, title)` behavior in `runner/tool_dispatch.py` and autowake in
`runner/app.py`. Add stable lifecycle projection hooks only; do not introduce a
new scheduler, retry loop, or direct Worker-to-Worker channel.

- [ ] **Step 5: Run native execution regressions and commit**

Run: `.venv/bin/python -m pytest tests/e2e/test_multi_agent_native_execution_e2e.py tests/e2e/test_subagent_autowake_e2e.py tests/runner/test_app_sessions_native_supervision.py -q`
Expected: PASS.

```bash
git add tests/e2e/test_multi_agent_native_execution_e2e.py tests/e2e/test_subagent_autowake_e2e.py omnigent/runner omnigent/runs
git commit -m "test: verify native multi-agent concurrency and autowake"
```

### Task 3: Prove Workspace selection and multi-repository worktree isolation

**Files:**
- Create: `tests/e2e/test_multi_agent_workspace_e2e.py`
- Modify: `tests/workspaces/test_multirepo_worktree_lease.py`

- [ ] **Step 1: Write the failing multi-repository test**

Build a temporary requirement directory containing two sibling Git repositories
and a Workspace manifest. Start two child Sessions with distinct titles and
assert each repository receives a child-owned worktree, branches and paths do
not collide, changes stay inside the registered root, and the root Session keeps
the immutable `workspace_id` selected when the Run started.

- [ ] **Step 2: Add restart recovery coverage**

Persist active leases, recreate the store/manager, assert leases can be listed
and released after restart, and verify switching the Feishu thread default
Workspace affects only the next Run.

- [ ] **Step 3: Run tests and verify the durable-lease assertion fails**

Run: `.venv/bin/python -m pytest tests/e2e/test_multi_agent_workspace_e2e.py tests/workspaces/test_multirepo_worktree_lease.py -q`
Expected: FAIL on restart recovery before the durable lease store is wired.

- [ ] **Step 4: Wire real child Session identity to the existing lease boundary**

Derive lease ownership server-side from `child_session_id` and Attempt identity;
never trust an arbitrary client-provided owner. Keep the current Workspace path
validation and create one lease per repository required by the Run.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/python -m pytest tests/e2e/test_multi_agent_workspace_e2e.py tests/workspaces tests/server/test_workspace_routes.py -q`
Expected: PASS.

```bash
git add tests/e2e/test_multi_agent_workspace_e2e.py tests/workspaces omnigent/workspaces omnigent/stores/worktree_lease_store
git commit -m "test: verify multi-repository workspace isolation"
```

### Task 4: Prove Agent-scoped Feishu install, routing and surface behavior

**Files:**
- Create: `tests/e2e/test_multi_agent_feishu_e2e.py`
- Modify: `tests/server/test_feishu_routes.py`
- Modify: `tests/integrations/lark/test_adapter_router.py`
- Modify: `tests/integrations/lark/test_surface.py`

- [ ] **Step 1: Write failing Agent-scoped installation tests**

Assert a cloned user Agent can begin and poll Device Flow, built-in Polly cannot
be connected directly, installation state remains after store recreation, and
all status responses redact credentials.

- [ ] **Step 2: Write failing inbound and surface tests**

Deliver duplicate signed Feishu messages and assert exactly one root Run is
created for the bound `agent_id`. A message naming a Worker must still enter the
root Coordinator. Assert surface provisioning is idempotent and exposes the
approved permanent actions: new task, Workspace, active Runs, approvals, help,
and reconnect/status.

- [ ] **Step 3: Run tests before wiring**

Run: `.venv/bin/python -m pytest tests/e2e/test_multi_agent_feishu_e2e.py tests/server/test_feishu_routes.py tests/integrations/lark/test_adapter_router.py tests/integrations/lark/test_surface.py -q`
Expected: FAIL on Team-scoped route or binding fields.

- [ ] **Step 4: Complete Agent-scoped test wiring**

Use the production Feishu installation/binding stores and Run service with a
fake external Feishu transport. Preserve signature, timestamp, nonce and event
deduplication; do not bypass the adapter to call the Coordinator directly.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/python -m pytest tests/e2e/test_multi_agent_feishu_e2e.py tests/server/test_feishu_routes.py tests/integrations/lark -q`
Expected: PASS.

```bash
git add tests/e2e/test_multi_agent_feishu_e2e.py tests/server/test_feishu_routes.py tests/integrations/lark omnigent/integrations/lark omnigent/server/routes/feishu.py
git commit -m "test: verify agent-scoped feishu workflow"
```

### Task 5: Verify durable Run projection and Inspector contract

**Files:**
- Modify: `tests/server/integration/test_run_projection.py`
- Create: `web/src/components/runs/RunInspector.integration.test.tsx`
- Modify: `web/src/pages/RunInspectorPage.test.tsx`

- [ ] **Step 1: Add failing projection assertions**

From the native execution in Task 2, assert one Run references the immutable
Agent version/digest and root Session, each explicit dispatch creates one Task,
each Worker turn creates one Attempt, replayed events are idempotent, and no
dependency is invented without an explicit causal event.

- [ ] **Step 2: Add failing Inspector assertions**

Render the API payload and assert Agent/version/digest, Workspace, root Session,
parallel timing, Worker/purpose/harness/model, failure diagnostic, artifact and
Session links are visible. Assert the event query is paginated rather than
embedding full tool/chat logs.

- [ ] **Step 3: Run backend and frontend tests before fixes**

Run: `.venv/bin/python -m pytest tests/server/integration/test_run_projection.py -q && pnpm --dir web test -- src/components/runs/RunInspector.integration.test.tsx src/pages/RunInspectorPage.test.tsx`
Expected: at least one new projection or Inspector assertion FAILS.

- [ ] **Step 4: Complete projection-to-UI contract mapping**

Adjust only the Run response DTO, Agent-scoped hooks, and Inspector presentation;
retain Session APIs as the source for detailed logs.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/python -m pytest tests/server/integration/test_run_projection.py tests/runs tests/stores/test_run_store.py -q && pnpm --dir web test -- src/components/runs/RunInspector.integration.test.tsx src/pages/RunInspectorPage.test.tsx`
Expected: PASS.

```bash
git add tests/server/integration/test_run_projection.py web/src/components/runs web/src/pages/RunInspectorPage.test.tsx web/src/lib/runsApi.ts web/src/hooks/useAgentRuns.ts
git commit -m "test: verify run projection inspector contract"
```

### Task 6: Add browser E2E for Builder, localization and Run flow

**Files:**
- Create: `tests/e2e_ui/multi_agents/test_multi_agent_builder.py`
- Create: `tests/e2e_ui/multi_agents/test_multi_agent_run.py`

- [ ] **Step 1: Write the failing Builder browser flow**

Open `/multi-agents`, assert the Polly card is read-only, use its template,
rename the copy, add/copy/rename a Worker, change one structured field, edit an
unknown YAML field in Advanced, save, reload, and export. Assert the copied card
shows the new version, worker count, valid status, and Feishu button.

- [ ] **Step 2: Write localization and draft-stability assertions**

Switch English to Simplified Chinese while the editor is dirty. Assert all new
navigation/actions/help/errors change language, YAML keys and model IDs do not,
and the unsaved draft remains byte-equivalent. Switch back to English and save.

- [ ] **Step 3: Write the failing browser Run flow**

Select a registered multi-repository Workspace, start the copied Agent, wait for
two Worker Sessions, open each Session detail, then open Run Inspector and assert
the Run completes without a manual continuation comment.

- [ ] **Step 4: Run the focused UI E2E**

Run: `.venv/bin/python -m pytest tests/e2e_ui/multi_agents -v`
Expected before UI completion: FAIL at the first missing route/control; expected after completion: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e_ui/multi_agents
git commit -m "test(web): cover multi-agent builder and run flows"
```

### Task 7: Run the complete automated release gate

**Files:**
- Modify: `openapi.json` only when generated output changes

- [ ] **Step 1: Verify migrations and backend suites**

Run:

```bash
.venv/bin/alembic -c omnigent/db/alembic.ini heads
.venv/bin/python -m pytest tests/agent_bundles tests/runs tests/workspaces tests/integrations/lark tests/server/test_agent_bundle_routes.py tests/server/test_feishu_routes.py tests/server/integration/test_run_projection.py tests/e2e/test_multi_agent_native_execution_e2e.py tests/e2e/test_multi_agent_workspace_e2e.py tests/e2e/test_multi_agent_feishu_e2e.py -q
.venv/bin/ruff check omnigent tests
.venv/bin/mypy omnigent
```

Expected: one Alembic head; tests and Ruff PASS. MyPy must PASS, or only the
repository's pre-existing generated protobuf-stub diagnostics may be reported
with the exact unchanged file/count recorded in the acceptance document.

- [ ] **Step 2: Verify the Web application**

Run:

```bash
pnpm --dir web test
pnpm --dir web type-check
pnpm --dir web lint
pnpm --dir web build
```

Expected: PASS with no newly introduced warnings or translation parity errors.

- [ ] **Step 3: Verify generated contracts and patch hygiene**

Run:

```bash
.venv/bin/python scripts/dump_openapi.py
git diff --check
git status --short
```

Expected: OpenAPI contains the Bundle, Agent-scoped Feishu and Run routes;
`git diff --check` passes; status contains only intentional files.

- [ ] **Step 4: Commit generated contract changes**

```bash
git add openapi.json
git diff --cached --quiet || git commit -m "docs: update multi-agent api contract"
```

### Task 8: Perform final local in-app browser acceptance

**Files:**
- Create: `docs/superpowers/plans/2026-08-04-multi-agent-browser-acceptance.md`

- [ ] **Step 1: Start the production-shaped local server**

Run the repository-supported Web build and host command using the current
`team-harness` branch and a persistent local database. Confirm:

```bash
curl -fsS http://127.0.0.1:6767/health
curl -fsS http://127.0.0.1:6767/v1/agents
```

Expected: HTTP 200 and the Agent catalog includes built-in Polly.

- [ ] **Step 2: Use the right-side in-app browser for real interaction**

Navigate to `http://127.0.0.1:6767/multi-agents` and perform, without DOM
shortcuts: inspect Polly; clone it; edit Coordinator and Worker fields; verify
Default model remains omitted; edit/save/reload Advanced YAML; observe the new
card; switch English/Chinese; select a multi-repository Workspace; start a Run;
open both Worker Session details; confirm automatic continuation; open Run
Inspector; open Agent-scoped Feishu connection and verify Device Flow reaches a
real QR/pending state without losing the QR while polling.

- [ ] **Step 3: Record observable evidence**

Create the acceptance Markdown with timestamp, branch/commit, Agent ID/version/
digest, Workspace ID, Run ID, root and child Session IDs, parallel timing,
autowake outcome, localization checks, Feishu installation state, browser URLs,
and any external credential boundary. Never record tokens, QR payloads, or
credential ciphertext.

- [ ] **Step 4: Verify the record and final tree, then commit**

Run: `git diff --check && git status --short`
Expected: PASS and only the acceptance record is uncommitted.

```bash
git add docs/superpowers/plans/2026-08-04-multi-agent-browser-acceptance.md
git commit -m "test: record multi-agent browser acceptance"
```
