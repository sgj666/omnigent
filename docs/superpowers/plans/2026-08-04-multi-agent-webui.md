# Multi-Agent WebUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary Team JSON screens with an Omnigent-native Multi-Agent catalog and lossless Agent Bundle editor that can visually configure Polly-shaped Coordinator and Worker files in English and Simplified Chinese.

**Architecture:** The browser treats the server-side Bundle Draft as the only editable source. TanStack Query loads lightweight card summaries separately from full Bundle drafts; `AgentConfigForm` emits typed field/file patches, while a lazy Monaco editor handles raw files and diagnostics. Built-in templates remain read-only and can only be cloned.

**Tech Stack:** React, TypeScript, React Router, TanStack Query, i18next/react-i18next, shadcn-style existing UI primitives, Monaco, Vitest/Testing Library, Playwright.

---

## File map

- `web/src/lib/multiAgentApi.ts`: Agent Bundle summary, draft, schema, patch, clone, import/export and validation client.
- `web/src/hooks/useMultiAgents.ts`: catalog/detail queries, mutations and cache invalidation.
- `web/src/components/multi-agents/MultiAgentCard.tsx`: persisted Bundle summary card.
- `web/src/pages/MultiAgentsPage.tsx`: catalog, template clone, import and empty/error states.
- `web/src/pages/MultiAgentDetailPage.tsx`: versioned draft shell, validation, save and conflict handling.
- `web/src/components/multi-agents/AgentConfigForm.tsx`: schema-driven Coordinator/Worker form kernel.
- `web/src/components/multi-agents/WorkerEditor.tsx`: Worker select/add/copy/rename/delete UI.
- `web/src/components/multi-agents/BundleYamlEditor.tsx`: lazy Monaco file editor and diagnostics.
- `web/src/components/multi-agents/FeishuConnectButton.tsx`: Agent-scoped Feishu entry.
- `web/src/i18n/locales/{en,zh-CN}/multiAgent.json`: new feature translations.
- `web/src/App.tsx`, `web/src/shell/Sidebar.tsx`: `/multi-agents` routes and navigation.

### Task 1: Add typed Bundle API and query hooks

**Files:**
- Create: `web/src/lib/multiAgentApi.ts`
- Create: `web/src/lib/multiAgentApi.test.ts`
- Create: `web/src/hooks/useMultiAgents.ts`
- Create: `web/src/hooks/useMultiAgents.test.tsx`

- [ ] **Step 1: Write failing API contract tests**

Test list/detail separation, clone, patch with `expected_version`, validate,
worker operations, import/export, deletion and structured diagnostics. Assert
that export preserves binary response handling and that a 409 response exposes
the server version without converting it to a generic message.

- [ ] **Step 2: Run and verify missing-module failures**

Run: `pnpm --dir web test -- src/lib/multiAgentApi.test.ts src/hooks/useMultiAgents.test.tsx`
Expected: FAIL because the API and hooks do not exist.

- [ ] **Step 3: Implement exact DTOs and query keys**

Define `MultiAgentSummary`, `AgentBundleDraft`, `AgentBundleFile`,
`AgentFormSchema`, `AgentBundlePatch`, `BundleDiagnostic`, and
`AgentVersionConflict`. Use `['multi-agents']` for the card catalog and
`['multi-agents', agentId]` for a draft. Successful create/update/clone/delete
must invalidate those keys and `['available-agents']` so the new persistent
Bundle immediately appears in the existing New Chat picker.

- [ ] **Step 4: Run tests and type-check**

Run: `pnpm --dir web test -- src/lib/multiAgentApi.test.ts src/hooks/useMultiAgents.test.tsx && pnpm --dir web type-check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/multiAgentApi.ts web/src/lib/multiAgentApi.test.ts web/src/hooks/useMultiAgents.ts web/src/hooks/useMultiAgents.test.tsx
git commit -m "feat(web): add multi-agent bundle client"
```

### Task 2: Replace Teams navigation and routes with Multi-Agent

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/shell/Sidebar.tsx`
- Modify: `web/src/shell/Sidebar.test.tsx`
- Create: `web/src/pages/MultiAgentsPage.tsx`
- Create: `web/src/pages/MultiAgentDetailPage.tsx`
- Create: `web/src/pages/MultiAgentsRoutes.test.tsx`

- [ ] **Step 1: Write failing route and navigation tests**

Assert `/multi-agents`, `/multi-agents/new`, and `/multi-agents/:agentId` render
the correct page shells; the sidebar shows `Multi-Agent` in the existing Teams
position and uses the current active styles. Assert no production navigation
link points to `/teams`.

- [ ] **Step 2: Run and verify failures**

Run: `pnpm --dir web test -- src/pages/MultiAgentsRoutes.test.tsx src/shell/Sidebar.test.tsx`
Expected: FAIL on missing route and navigation label.

- [ ] **Step 3: Add routes using existing routing primitives**

Register lazy page modules in `App.tsx`; use `PageScroll`,
`web/src/lib/routing.tsx`, and existing button/layout primitives. Replace the
Teams sidebar item without adding a second top-level concept. Keep `/runs/:id`
available and make its back link target `/multi-agents`.

- [ ] **Step 4: Run route tests**

Run: `pnpm --dir web test -- src/pages/MultiAgentsRoutes.test.tsx src/shell/Sidebar.test.tsx src/pages/RunInspectorPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/shell/Sidebar.tsx web/src/shell/Sidebar.test.tsx web/src/pages/MultiAgentsPage.tsx web/src/pages/MultiAgentDetailPage.tsx web/src/pages/MultiAgentsRoutes.test.tsx web/src/pages/RunInspectorPage.tsx
git commit -m "feat(web): add multi-agent routes and navigation"
```

### Task 3: Build the persisted Bundle card catalog

**Files:**
- Create: `web/src/components/multi-agents/MultiAgentCard.tsx`
- Create: `web/src/components/multi-agents/MultiAgentCard.test.tsx`
- Modify: `web/src/pages/MultiAgentsPage.tsx`
- Create: `web/src/pages/MultiAgentsPage.test.tsx`

- [ ] **Step 1: Write failing card behavior tests**

Assert each card displays name, description, Coordinator/Harness, model source,
Worker count, Skills/MCP count, version, update time, validation, Feishu and
recent Run state. Built-in Polly must show a read-only badge and only Run/View/
Use this template/Export actions; a user Bundle exposes Run/Edit/Clone/Export/
Delete and Connect Feishu according to validation state.

- [ ] **Step 2: Write loading, error and empty-state tests**

Assert the page never mixes session-scoped temporary Agents into the catalog,
keeps card layout stable while loading, gives retry on API failure, and offers
Use Polly template or Import from the empty state.

- [ ] **Step 3: Run and verify component failures**

Run: `pnpm --dir web test -- src/components/multi-agents/MultiAgentCard.test.tsx src/pages/MultiAgentsPage.test.tsx`
Expected: FAIL because card components are absent.

- [ ] **Step 4: Implement using existing Card/Badge/Button/Dialog components**

Keep the approved gallery density and current Omnigent color/spacing tokens.
Navigate by card click, stop propagation for action menus, confirm deletion,
and clone built-ins through the Bundle API rather than rebuilding YAML in the
browser.

- [ ] **Step 5: Run, verify and commit**

Run: `pnpm --dir web test -- src/components/multi-agents/MultiAgentCard.test.tsx src/pages/MultiAgentsPage.test.tsx`
Expected: PASS.

```bash
git add web/src/components/multi-agents/MultiAgentCard.tsx web/src/components/multi-agents/MultiAgentCard.test.tsx web/src/pages/MultiAgentsPage.tsx web/src/pages/MultiAgentsPage.test.tsx
git commit -m "feat(web): show multi-agent bundle cards"
```

### Task 4: Build the shared schema-driven Agent configuration form

**Files:**
- Create: `web/src/components/multi-agents/AgentConfigForm.tsx`
- Create: `web/src/components/multi-agents/AgentConfigForm.test.tsx`
- Create: `web/src/components/multi-agents/SchemaField.tsx`
- Create: `web/src/components/multi-agents/SchemaField.test.tsx`

- [ ] **Step 1: Write failing omission/default tests**

Render form schema fields for identity, prompt/instructions, executor/harness/
model, tools, Skills, MCP, params, policies, sandbox, terminals, environment,
guardrails, async/timers/spawn and session sharing. Assert `Use local default`
emits a `remove` patch for `/executor/model`; explicit model, `false`, `0`, empty
list and `null` remain distinct values.

- [ ] **Step 2: Write secret and generic-tree tests**

Assert secret values render only configured/reference state and are never
placed in text inputs or snapshots. Unknown schema objects must remain editable
through `generic-tree` without deleting unrecognized sibling fields.

- [ ] **Step 3: Run and verify missing component failures**

Run: `pnpm --dir web test -- src/components/multi-agents/AgentConfigForm.test.tsx src/components/multi-agents/SchemaField.test.tsx`
Expected: FAIL because the form kernel does not exist.

- [ ] **Step 4: Implement a pure draft-to-patch form**

Accept schema, file path, parsed data, diagnostics and `onPatch`; keep field
labels separate from enum/YAML values. Reuse existing `Input`, `Textarea`,
`Select`, `Tabs`, `ConfigRow`, harness labels and model option hooks, but do not
reuse the run-override `HarnessConfigModal` or browser-side `buildAgentBundle`.

- [ ] **Step 5: Run and commit**

Run: `pnpm --dir web test -- src/components/multi-agents/AgentConfigForm.test.tsx src/components/multi-agents/SchemaField.test.tsx && pnpm --dir web type-check`
Expected: PASS.

```bash
git add web/src/components/multi-agents/AgentConfigForm.tsx web/src/components/multi-agents/AgentConfigForm.test.tsx web/src/components/multi-agents/SchemaField.tsx web/src/components/multi-agents/SchemaField.test.tsx
git commit -m "feat(web): configure agent bundles from schema"
```

### Task 5: Add Coordinator and Worker file operations to the editor

**Files:**
- Create: `web/src/components/multi-agents/WorkerEditor.tsx`
- Create: `web/src/components/multi-agents/WorkerEditor.test.tsx`
- Modify: `web/src/pages/MultiAgentDetailPage.tsx`
- Create: `web/src/pages/MultiAgentDetailPage.test.tsx`

- [ ] **Step 1: Write failing editor-shell tests**

Assert root `config.yaml` is labeled Coordinator, `agents/*/config.yaml` entries
are Workers, clicking either renders the same `AgentConfigForm`, and the header
shows name, dirty state, version, validation, Save, Run, Export and the reserved
Agent-scoped Connect Feishu button.

- [ ] **Step 2: Write failing Worker operation tests**

Assert add from minimal template, copy, rename and delete call server Worker
operations; rename updates displayed references atomically; deleting a
referenced Worker requires a diagnostic confirmation; any failed operation
keeps the previous draft unchanged.

- [ ] **Step 3: Run and verify failures**

Run: `pnpm --dir web test -- src/components/multi-agents/WorkerEditor.test.tsx src/pages/MultiAgentDetailPage.test.tsx`
Expected: FAIL on missing Worker editor and draft shell.

- [ ] **Step 4: Implement editor navigation and save state**

Use a left Coordinator/Workers navigation rail inside the page, not a new
global concept. Send accumulated typed patches with `expected_version`; on
success replace the draft/version from the server; on 409 show Reload and
Export my draft actions without silently overwriting either version.

- [ ] **Step 5: Run and commit**

Run: `pnpm --dir web test -- src/components/multi-agents/WorkerEditor.test.tsx src/pages/MultiAgentDetailPage.test.tsx`
Expected: PASS.

```bash
git add web/src/components/multi-agents/WorkerEditor.tsx web/src/components/multi-agents/WorkerEditor.test.tsx web/src/pages/MultiAgentDetailPage.tsx web/src/pages/MultiAgentDetailPage.test.tsx
git commit -m "feat(web): edit coordinator and worker bundles"
```

### Task 6: Add lossless Advanced YAML and file-tree editing

**Files:**
- Create: `web/src/components/multi-agents/BundleYamlEditor.tsx`
- Create: `web/src/components/multi-agents/BundleYamlEditor.test.tsx`
- Create: `web/src/components/multi-agents/BundleFileTree.tsx`
- Create: `web/src/components/multi-agents/BundleFileTree.test.tsx`
- Modify: `web/src/pages/MultiAgentDetailPage.tsx`

- [ ] **Step 1: Write failing raw-draft and diagnostic tests**

Assert selecting a YAML/Markdown/text file loads its exact server text; editing
emits `replace_file` without browser serialization; invalid YAML remains visible
with file/line/column diagnostics and disables Save; returning to Basic uses the
latest valid parsed draft without discarding invalid raw text.

- [ ] **Step 2: Write lazy loading and validation race tests**

Assert Monaco is not in the catalog bundle, validation is debounced, an older
response cannot overwrite newer diagnostics, non-text files are download-only,
and untouched files never appear in the patch set.

- [ ] **Step 3: Run and verify missing-module failures**

Run: `pnpm --dir web test -- src/components/multi-agents/BundleYamlEditor.test.tsx src/components/multi-agents/BundleFileTree.test.tsx`
Expected: FAIL because the editors do not exist.

- [ ] **Step 4: Implement a standalone lazy Monaco editor**

Reuse `ensureMonacoReady`, `ensureLanguage`, and theme resolution from existing
Monaco setup, but do not use `MonacoCodeEditor` session filesystem permissions,
autosave or comments. Display schema/native validation diagnostics as Monaco
markers and an accessible error list.

- [ ] **Step 5: Run tests, build and commit**

Run: `pnpm --dir web test -- src/components/multi-agents/BundleYamlEditor.test.tsx src/components/multi-agents/BundleFileTree.test.tsx src/pages/MultiAgentDetailPage.test.tsx && pnpm --dir web build`
Expected: PASS and a separate lazy editor chunk.

```bash
git add web/src/components/multi-agents/BundleYamlEditor.tsx web/src/components/multi-agents/BundleYamlEditor.test.tsx web/src/components/multi-agents/BundleFileTree.tsx web/src/components/multi-agents/BundleFileTree.test.tsx web/src/pages/MultiAgentDetailPage.tsx
git commit -m "feat(web): edit agent bundle yaml losslessly"
```

### Task 7: Add Agent-scoped Feishu and Run actions

**Files:**
- Create: `web/src/components/multi-agents/FeishuConnectButton.tsx`
- Create: `web/src/components/multi-agents/FeishuConnectButton.test.tsx`
- Modify: `web/src/lib/feishuApi.ts`
- Modify: `web/src/hooks/useFeishuInstall.ts`
- Modify: `web/src/pages/MultiAgentsPage.tsx`
- Modify: `web/src/pages/MultiAgentDetailPage.tsx`

- [ ] **Step 1: Write failing Agent-scope tests**

Assert user Bundle actions call `/v1/agents/{agentId}/feishu/*`, built-in Polly
offers Use this template instead of direct binding, a pending QR remains visible
during polling, connected/partial/error states are explicit, and reinitialize/
disconnect actions use the same Agent ID.

- [ ] **Step 2: Write failing Run action tests**

Assert Run opens the existing start flow with the persistent Agent preselected,
requires a Workspace for a new Run, and recent Run links open `/runs/:runId`.

- [ ] **Step 3: Run and verify Team-scope failures**

Run: `pnpm --dir web test -- src/components/multi-agents/FeishuConnectButton.test.tsx src/pages/MultiAgentsPage.test.tsx src/pages/MultiAgentDetailPage.test.tsx`
Expected: FAIL while hooks still use Team-scoped routes.

- [ ] **Step 4: Switch the client to Agent-scoped routes**

Reuse existing QR, polling and surface visuals with Agent DTOs. Remove fake
surface state from the old Team form. Route every inbound task to the fixed
Coordinator; Worker names are never Feishu destinations.

- [ ] **Step 5: Run and commit**

Run: `pnpm --dir web test -- src/components/multi-agents/FeishuConnectButton.test.tsx src/hooks/useFeishuInstall.test.tsx src/pages/MultiAgentsPage.test.tsx src/pages/MultiAgentDetailPage.test.tsx`
Expected: PASS.

```bash
git add web/src/components/multi-agents/FeishuConnectButton.tsx web/src/components/multi-agents/FeishuConnectButton.test.tsx web/src/lib/feishuApi.ts web/src/hooks/useFeishuInstall.ts web/src/pages/MultiAgentsPage.tsx web/src/pages/MultiAgentDetailPage.tsx
git commit -m "feat(web): connect multi-agents to feishu"
```

### Task 8: Localize the feature and remove the active Team UI path

**Files:**
- Create: `web/src/i18n/locales/en/multiAgent.json`
- Create: `web/src/i18n/locales/zh-CN/multiAgent.json`
- Modify: `web/src/i18n/resources.ts`
- Modify: `web/src/i18n/resources.test.ts`
- Modify: `web/src/pages/MultiAgentsPage.tsx`
- Modify: `web/src/pages/MultiAgentDetailPage.tsx`
- Modify: `web/src/shell/Sidebar.tsx`
- Delete after import scan: `web/src/pages/TeamsPage.tsx`
- Delete after import scan: `web/src/pages/TeamDetailPage.tsx`
- Delete after import scan: `web/src/components/teams/TeamForm.tsx`
- Delete after import scan: `web/src/components/teams/AgentProfileList.tsx`

- [ ] **Step 1: Add failing translation parity and language-switch tests**

Assert the `multiAgent` namespace has identical non-empty keys and interpolation
variables in English and Chinese. While a form is dirty, switch language and
assert labels/errors/help change while draft values, YAML keys, names, model/
harness IDs, commands and paths remain unchanged.

- [ ] **Step 2: Run and verify namespace failures**

Run: `pnpm --dir web test -- src/i18n/resources.test.ts src/pages/MultiAgentsPage.test.tsx src/pages/MultiAgentDetailPage.test.tsx`
Expected: FAIL because the namespace is not registered.

- [ ] **Step 3: Add translations and remove old active imports**

Register the namespace in both resources and translate only new UI. Use `rg` to
prove old Team pages/forms have no production imports before deleting them.
Keep backend legacy diagnostics and migrations; this task removes only the
parallel Web configuration surface.

- [ ] **Step 4: Run the full Web gate**

Run:

```bash
pnpm --dir web test
pnpm --dir web type-check
pnpm --dir web lint
pnpm --dir web build
git diff --check
```

Expected: PASS; no visible new feature text is hard-coded in either language.

- [ ] **Step 5: Commit**

```bash
git add web/src/i18n web/src/pages web/src/components/multi-agents web/src/components/teams web/src/shell/Sidebar.tsx
git commit -m "feat(web): localize multi-agent bundle builder"
```
