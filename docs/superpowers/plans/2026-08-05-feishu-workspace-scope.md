# Feishu Workspace Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require a usable local workspace root for each Feishu thread, while allowing a non-Git root to contain multiple optional Git projects.

**Architecture:** A thread binding stores a workspace root and an optional nested Git project. The router returns a workspace setup response before any Core session call, then creates and continues a Core Session through the supported Sessions API.

**Tech Stack:** Python, FastAPI, httpx, aiosqlite, pytest, Feishu interactive cards.

## Global Constraints

- A non-Git local directory is a valid workspace root.
- No Feishu message may create a Core session without a selected root.
- A root can contain multiple Git repositories; project selection is optional and per thread.
- Do not call retired `/v1/runs` routes.
- Preserve existing bindings and unrelated dirty files.

---

### Task 1: Move the Feishu runtime client to Core Sessions

**Files:**
- Modify: `integrations/feishu/src/omnigent_feishu/core_client.py`
- Test: `integrations/feishu/tests/test_provider.py`

**Interfaces:**
- Produces `SessionCreateCommand(agent_id, workspace_id, host_id)`.
- Produces `CoreClient.create_session(command)` posting JSON to `/v1/sessions`.

- [ ] **Step 1: Write the failing request contract test**

```python
await client.create_session(SessionCreateCommand(agent_id="agent", workspace_id="ws", host_id="host"))
assert captured["path"] == "/v1/sessions"
```

- [ ] **Step 2: Run it**

Run: `pytest integrations/feishu/tests/test_provider.py -k create_session_uses_sessions_api -v`

Expected: FAIL because the client currently posts `/v1/runs`.

- [ ] **Step 3: Implement the minimal client replacement**

```python
async def create_session(self, command: SessionCreateCommand) -> Any:
    return await self._request("POST", "/v1/sessions", json=command.payload())
```

- [ ] **Step 4: Re-run the focused test**

Run: `pytest integrations/feishu/tests/test_provider.py -k create_session_uses_sessions_api -v`

Expected: PASS.

### Task 2: Persist root and optional Git project separately

**Files:**
- Modify: `integrations/feishu/src/omnigent_feishu/models.py`
- Modify: `integrations/feishu/src/omnigent_feishu/store.py`
- Test: `integrations/feishu/tests/test_provider.py`

**Interfaces:**
- Produces `ThreadBinding.project_repository_id: str | None`.
- Produces `set_binding_scope(binding_id, workspace_id, project_repository_id=None)`.

- [ ] **Step 1: Write a failing persistence test**

```python
await store.set_binding_scope(binding.id, "workspace", "project")
saved = await store.get_binding("installation", "chat", "")
assert saved.workspace_id == "workspace"
assert saved.project_repository_id == "project"
```

- [ ] **Step 2: Run it**

Run: `pytest integrations/feishu/tests/test_provider.py -k binding_scope -v`

Expected: FAIL because the optional project field is absent.

- [ ] **Step 3: Add an additive SQLite migration and scope setter**

Add `project_repository_id TEXT` only when missing. Existing bindings retain their root and session state.

- [ ] **Step 4: Re-run the focused test**

Run: `pytest integrations/feishu/tests/test_provider.py -k binding_scope -v`

Expected: PASS.

### Task 3: Gate routing, provide setup UI, and create sessions correctly

**Files:**
- Modify: `integrations/feishu/src/omnigent_feishu/router.py`
- Modify: `integrations/feishu/src/omnigent_feishu/cards.py`
- Modify: `integrations/feishu/src/omnigent_feishu/realtime.py`
- Test: `integrations/feishu/tests/test_provider.py`

**Interfaces:**
- Produces route payload `{ "setup_required": True, "code": "workspace_required" }` without a Core call.
- Consumes signed workspace-root and optional-project actions.

- [ ] **Step 1: Write a failing router test for an unconfigured binding**

```python
result = await router.route(message)
assert result.payload == {"setup_required": True, "code": "workspace_required"}
core.create_session.assert_not_awaited()
```

- [ ] **Step 2: Run it**

Run: `pytest integrations/feishu/tests/test_provider.py -k workspace_required -v`

Expected: FAIL because a message currently reaches `/v1/runs`.

- [ ] **Step 3: Implement guard and setup card**

Return `workspace_required` for a binding without root; send a concise card asking for a local root. Workspace actions save the root for only the active thread. The optional Git-project action saves a nested repository without invalidating a non-Git root.

- [ ] **Step 4: Create a session and post the message**

```python
created = await self._core.create_session(SessionCreateCommand(...))
session_id = str(created["id"])
await self._core.send_session_input(session_id, event.text)
```

Persist `session_id` as the binding's conversation continuity ID.

- [ ] **Step 5: Run the focused Feishu tests**

Run: `pytest integrations/feishu/tests/test_provider.py -v`

Expected: PASS.

### Task 4: Verify against the running local stack

**Files:**
- No source files expected.

- [ ] **Step 1: Run the package suite**

Run: `.venv/bin/python -m pytest integrations/feishu/tests -q`

Expected: PASS.

- [ ] **Step 2: Restart standalone Feishu and verify the real flow**

Send a message on an unconfigured binding and confirm it receives setup guidance instead of `CoreApiError`; select a non-Git root containing multiple projects; send a normal message and confirm a Core Session/reply; switch the optional Git project and verify the change is thread-local.

- [ ] **Step 3: Commit only task-owned files**

```bash
git add integrations/feishu/src/omnigent_feishu/core_client.py integrations/feishu/src/omnigent_feishu/router.py integrations/feishu/src/omnigent_feishu/cards.py integrations/feishu/src/omnigent_feishu/realtime.py integrations/feishu/src/omnigent_feishu/store.py integrations/feishu/src/omnigent_feishu/models.py integrations/feishu/tests/test_provider.py docs/superpowers/plans/2026-08-05-feishu-workspace-scope.md
git commit -m "fix: require feishu workspace scope before session creation"
```
