# Multi-Agent Bundle Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable, editable Agent Template Bundle CRUD with round-trip YAML preservation, worker-directory operations, optimistic versions, native validation, clone/import/export, and schema metadata.

**Architecture:** `AgentStore` and `ArtifactStore` remain the persistence boundary. A new `agent_bundles` package opens stored tarballs as round-trip documents, applies explicit file/JSON-pointer patches, repacks deterministically, and always calls the existing `validate_agent_bundle` before an atomic store/cache update. The existing read-only agent catalog is extended; no Team JSON is written.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, existing AgentStore/ArtifactStore/AgentCache, `ruamel.yaml`, Pytest, Ruff, MyPy.

---

## File map

- `omnigent/agent_bundles/document.py`: safe Bundle file tree, round-trip YAML and deterministic tar serialization.
- `omnigent/agent_bundles/patches.py`: typed file/JSON-pointer patch operations.
- `omnigent/agent_bundles/workers.py`: atomic Worker add/copy/rename/delete operations.
- `omnigent/agent_bundles/service.py`: AgentStore/ArtifactStore/AgentCache transaction boundary.
- `omnigent/agent_bundles/schema.py`: server-owned form field catalog and generic field metadata.
- `omnigent/server/routes/agent_bundles.py`: Template Bundle CRUD, validate, clone, import and export API.
- `omnigent/server/schemas.py`: API wire models.
- `omnigent/stores/agent_store/*`: optimistic update and metadata rename.
- `omnigent/server/app.py`: route wiring.
- `tests/agent_bundles/*`, `tests/server/test_agent_bundle_routes.py`, `tests/stores/test_agent_store.py`: behavior and API tests.

### Task 1: Add the round-trip YAML dependency and Bundle document tests

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `omnigent/agent_bundles/__init__.py`
- Create: `omnigent/agent_bundles/document.py`
- Create: `tests/agent_bundles/test_document.py`

- [ ] **Step 1: Write the failing preservation test**

```python
def test_untouched_files_and_yaml_comments_survive_round_trip() -> None:
    original = make_bundle({
        "config.yaml": "# coordinator\nspec_version: 1\nname: polly\ncustom_future: keep\n",
        "skills/fanout/SKILL.md": "# fanout\n",
    })
    doc = BundleDocument.from_bytes(original)
    doc.replace_yaml_value("config.yaml", ("name",), "my-polly")
    reopened = BundleDocument.from_bytes(doc.to_bytes())
    assert "# coordinator" in reopened.read_text("config.yaml")
    assert "custom_future: keep" in reopened.read_text("config.yaml")
    assert reopened.read_text("skills/fanout/SKILL.md") == "# fanout\n"
```

- [ ] **Step 2: Verify the test fails because the package does not exist**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_document.py -q`
Expected: FAIL with `ModuleNotFoundError: omnigent.agent_bundles`.

- [ ] **Step 3: Add the runtime dependency and minimal document**

Add `"ruamel.yaml>=0.18,<1"` immediately after PyYAML in `pyproject.toml`, run
`uv lock`, and implement:

Implement the concrete methods `BundleDocument.from_bytes(bundle)`,
`read_text(path)`, `replace_yaml_value(path, pointer, value)`, and `to_bytes()`.
Use `extract_safe` for input, reject duplicate archive paths, store every regular
file as bytes, configure `YAML(typ="rt").preserve_quotes = True`, and serialize
tar entries in sorted path order with fixed uid/gid/mtime for stable digests.

- [ ] **Step 4: Run document tests**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_document.py tests/server/test_bundles.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock omnigent/agent_bundles tests/agent_bundles/test_document.py
git commit -m "feat: add round-trip agent bundle documents"
```

### Task 2: Implement typed patch operations and Advanced YAML replacement

**Files:**
- Create: `omnigent/agent_bundles/patches.py`
- Modify: `omnigent/agent_bundles/document.py`
- Create: `tests/agent_bundles/test_patches.py`

- [ ] **Step 1: Write failing tests for add/replace/remove and whole-file edits**

```python
def test_patch_distinguishes_default_from_explicit_false() -> None:
    doc = document("spec_version: 1\nname: a\nasync: false\n")
    apply_patches(doc, [BundlePatch(file="config.yaml", op="remove", path="/async")])
    assert "async:" not in doc.read_text("config.yaml")

def test_replace_file_keeps_invalid_yaml_for_diagnostics() -> None:
    doc = document("spec_version: 1\nname: a\n")
    apply_patches(doc, [BundlePatch(file="config.yaml", op="replace_file", value="name: [")])
    assert doc.read_text("config.yaml") == "name: ["
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_patches.py -q`
Expected: FAIL because `BundlePatch` is undefined.

- [ ] **Step 3: Implement the patch contract**

```python
@dataclass(frozen=True)
class BundlePatch:
    file: str
    op: Literal["add", "replace", "remove", "replace_file", "delete_file"]
    path: str = ""
    value: object | None = None
```

Decode RFC 6901 paths, reject `..`, absolute paths and non-UTF8 file replacement,
preserve missing-vs-null semantics, and raise `BundlePatchError(file, path, message)`.

- [ ] **Step 4: Run tests and lint**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_patches.py -q && .venv/bin/ruff check omnigent/agent_bundles tests/agent_bundles`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omnigent/agent_bundles tests/agent_bundles/test_patches.py
git commit -m "feat: apply lossless agent bundle patches"
```

### Task 3: Add atomic Worker directory operations

**Files:**
- Create: `omnigent/agent_bundles/workers.py`
- Create: `tests/agent_bundles/test_workers.py`

- [ ] **Step 1: Write failing Polly-shaped tests**

```python
def test_copy_worker_copies_directory_and_adds_root_reference() -> None:
    doc = polly_bundle_document()
    copy_worker(doc, source="codex", target="codex-reviewer")
    assert doc.exists("agents/codex-reviewer/config.yaml")
    assert doc.yaml_value("agents/codex-reviewer/config.yaml", ("name",)) == "codex-reviewer"
    assert "codex-reviewer" in doc.yaml_value("config.yaml", ("tools", "agents"))

def test_rename_worker_rejects_existing_target_without_partial_change() -> None:
    before = doc.to_bytes()
    with pytest.raises(WorkerEditError):
        rename_worker(doc, source="codex", target="claude_code")
    assert doc.to_bytes() == before
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_workers.py -q`
Expected: FAIL because Worker helpers do not exist.

- [ ] **Step 3: Implement copy/add/rename/delete on a cloned document**

Each operation must mutate a clone, update `tools.agents`, validate target names
against `^[A-Za-z0-9_.-]+$`, update the Worker `name`, then swap the clone into
the caller only after every file operation succeeds. Delete must return formal
YAML reference paths so the route can require confirmation.

- [ ] **Step 4: Run Worker and real Polly validation tests**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_workers.py tests/server/test_builtin_bundles.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omnigent/agent_bundles/workers.py tests/agent_bundles/test_workers.py
git commit -m "feat: edit bundled multi-agent workers"
```

### Task 4: Add optimistic AgentStore metadata updates

**Files:**
- Modify: `omnigent/stores/agent_store/__init__.py`
- Modify: `omnigent/stores/agent_store/sqlalchemy_store.py`
- Modify: `tests/stores/test_agent_store.py`

- [ ] **Step 1: Add failing version, rename and conflict tests**

```python
def test_update_template_checks_version_and_updates_metadata(agent_store):
    agent = agent_store.create(ID, "old", "old/hash", description="old desc")
    updated = agent_store.update_template(
        ID, bundle_location="new/hash", name="new", description="new desc", expected_version=1
    )
    assert updated is not None and updated.version == 2
    assert (updated.name, updated.description) == ("new", "new desc")
    with pytest.raises(AgentVersionConflict):
        agent_store.update_template(
            ID, bundle_location="other/hash", name="new", description="new desc", expected_version=1
        )
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/stores/test_agent_store.py -q`
Expected: FAIL because `update_template` and `AgentVersionConflict` do not exist.

- [ ] **Step 3: Implement one SQL conditional update transaction**

Add `AgentVersionConflict(agent_id, expected, actual)` and an abstract
`update_template`. In SQLAlchemy, check Template kind, enforce unique Template
name in the current workspace, update name/description/location, increment
version and set `updated_at` in the same managed session. Keep the existing
`update()` for Session-scoped call sites.

- [ ] **Step 4: Run store tests**

Run: `.venv/bin/python -m pytest tests/stores/test_agent_store.py tests/stores/test_conversation_store_split_db.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omnigent/stores/agent_store tests/stores/test_agent_store.py
git commit -m "feat: update agent templates optimistically"
```

### Task 5: Build the AgentBundleService transaction boundary

**Files:**
- Create: `omnigent/agent_bundles/service.py`
- Create: `tests/agent_bundles/test_service.py`

- [ ] **Step 1: Write failing create/update/clone/delete tests with in-memory stores**

```python
def test_update_validates_before_repointing_agent(service, stores) -> None:
    agent = service.create(valid_bundle("alpha"))
    original = stores.agent.get(agent.id)
    with pytest.raises(OmnigentError):
        service.update(agent.id, expected_version=1, patches=[replace_file("config.yaml", "[")])
    assert stores.agent.get(agent.id).bundle_location == original.bundle_location

def test_clone_does_not_copy_external_bindings(service) -> None:
    source = service.create(polly_bundle())
    clone = service.clone(source.id, name="my-polly")
    assert clone.id != source.id and clone.version == 1
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_service.py -q`
Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement service methods**

Implement concrete `AgentBundleService` methods for `get_draft`, `validate`,
`create`, `update`, `clone`, `export`, and `delete`. Use `generate_agent_id`,
`bundle_location`, `validate_agent_bundle`,
`artifact_store.put`, `agent_store.create/update_template`, and
`agent_cache.replace/evict`. Reject seeded IDs from update/delete. On store
failure, delete only the newly written unreferenced artifact. Never expand
tenant env vars during HTTP validation.

- [ ] **Step 4: Run service tests and static checks**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_service.py -q && .venv/bin/mypy omnigent/agent_bundles`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omnigent/agent_bundles/service.py tests/agent_bundles/test_service.py
git commit -m "feat: persist editable agent template bundles"
```

### Task 6: Define Bundle draft, diagnostic and patch API schemas

**Files:**
- Modify: `omnigent/server/schemas.py`
- Create: `tests/server/test_agent_bundle_schemas.py`

- [ ] **Step 1: Write failing Pydantic contract tests**

```python
def test_bundle_patch_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError):
        AgentBundlePatchRequest(expected_version=1, patches=[{"file": "../x", "op": "remove"}])

def test_diagnostic_carries_file_field_and_location() -> None:
    diagnostic = AgentBundleDiagnostic(
        severity="error", code="invalid_yaml", file="config.yaml",
        path="/executor", line=4, column=2, message="bad yaml"
    )
    assert diagnostic.file == "config.yaml"
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_agent_bundle_schemas.py -q`
Expected: FAIL because the models do not exist.

- [ ] **Step 3: Add explicit wire models**

Add `AgentBundleFile`, `AgentBundleDiagnostic`, `AgentBundleDraftObject`,
`AgentBundlePatchObject`, `AgentBundlePatchRequest`, `AgentBundleCloneRequest`,
and `AgentBundleValidationObject`. Do not use `dict[str, Any]` for top-level
responses; retain arbitrary YAML values only inside a named `data` field.

- [ ] **Step 4: Run schema tests**

Run: `.venv/bin/python -m pytest tests/server/test_agent_bundle_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omnigent/server/schemas.py tests/server/test_agent_bundle_schemas.py
git commit -m "feat: define agent bundle API schemas"
```

### Task 7: Expose Agent Template Bundle CRUD routes

**Files:**
- Create: `omnigent/server/routes/agent_bundles.py`
- Modify: `omnigent/server/routes/builtin_agents.py`
- Modify: `omnigent/server/app.py`
- Create: `tests/server/test_agent_bundle_routes.py`

- [ ] **Step 1: Write failing HTTP tests**

```python
def test_clone_builtin_polly_then_patch_model(client) -> None:
    polly = next(a for a in client.get("/v1/agents").json()["data"] if a["name"] == "polly")
    clone = client.post(f"/v1/agents/{polly['id']}/clone", json={"name": "my-polly"})
    assert clone.status_code == 201
    result = client.put(
        f"/v1/agents/{clone.json()['id']}",
        json={"expected_version": 1, "patches": [
            {"file": "agents/codex/config.yaml", "op": "remove", "path": "/executor/model"}
        ]},
    )
    assert result.status_code == 200 and result.json()["version"] == 2

def test_builtin_update_is_rejected(client, polly_id) -> None:
    response = client.put(f"/v1/agents/{polly_id}", json={"expected_version": 1, "patches": []})
    assert response.status_code == 400
```

- [ ] **Step 2: Verify route tests fail**

Run: `.venv/bin/python -m pytest tests/server/test_agent_bundle_routes.py -q`
Expected: FAIL with 404 responses.

- [ ] **Step 3: Register authenticated routes**

Implement list summary enrichment (`builtin`, `editable`, `worker_count`, digest),
get draft, validate upload, create/import upload, patch update, clone, delete and
gzip export. Call blocking service methods via `asyncio.to_thread`. Map
`AgentVersionConflict` to `ErrorCode.CONFLICT`/HTTP 409 and return structured
diagnostics for invalid YAML.

- [ ] **Step 4: Run route, security and existing session tests**

Run: `.venv/bin/python -m pytest tests/server/test_agent_bundle_routes.py tests/server/routes/test_builtin_agents.py tests/server/routes/test_sessions_upload_limits.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omnigent/server/routes/agent_bundles.py omnigent/server/routes/builtin_agents.py omnigent/server/app.py tests/server/test_agent_bundle_routes.py
git commit -m "feat: expose editable agent bundle APIs"
```

### Task 8: Publish the form schema and prove full Polly round-trip

**Files:**
- Create: `omnigent/agent_bundles/schema.py`
- Modify: `omnigent/server/routes/agent_bundles.py`
- Create: `tests/agent_bundles/test_schema.py`
- Create: `tests/server/test_agent_bundle_polly_roundtrip.py`

- [ ] **Step 1: Write schema coverage and real Polly tests**

```python
REQUIRED_PATHS = {
    "/spec_version", "/name", "/description", "/prompt", "/instructions",
    "/executor", "/tools", "/params", "/skills", "/os_env", "/terminals",
    "/guardrails", "/async", "/timers", "/spawn", "/agent_session_sharing",
}

def test_schema_exposes_every_supported_top_level_domain() -> None:
    paths = {field.path for field in build_agent_form_schema().fields}
    assert REQUIRED_PATHS <= paths

def test_real_polly_edit_preserves_workers_skills_comments_and_cli_validation(service) -> None:
    agent = service.create(pack_directory(Path("examples/polly")))
    service.update(agent.id, 1, [replace("config.yaml", "/description", "custom")])
    exported = service.export(agent.id)
    assert validate_agent_bundle(exported).name == "polly"
    assert b"spawn_bounds" in exported and b"skills/fanout/SKILL.md" in exported
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/agent_bundles/test_schema.py tests/server/test_agent_bundle_polly_roundtrip.py -q`
Expected: FAIL because schema metadata is absent.

- [ ] **Step 3: Implement a versioned schema catalog**

Return field path, type, group, required/default behavior, enum, secret flag,
translation key and Harness visibility. Complex mappings use `editor` values
`worker-list`, `mcp-list`, `policy-map`, `sandbox`, `terminal-map`, `params`, or
`generic-tree`; this guarantees every raw YAML object remains editable even
before a specialized widget exists.

- [ ] **Step 4: Run the backend gate**

Run:

```bash
.venv/bin/python -m pytest \
  tests/agent_bundles \
  tests/server/test_agent_bundle_schemas.py \
  tests/server/test_agent_bundle_routes.py \
  tests/server/test_agent_bundle_polly_roundtrip.py \
  tests/stores/test_agent_store.py -q
.venv/bin/ruff check omnigent/agent_bundles omnigent/server/routes/agent_bundles.py tests/agent_bundles tests/server/test_agent_bundle_routes.py
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 5: Commit**

```bash
git add omnigent/agent_bundles/schema.py omnigent/server/routes/agent_bundles.py tests/agent_bundles tests/server/test_agent_bundle_polly_roundtrip.py
git commit -m "feat: publish multi-agent form schema"
```
