# Feishu Team Harness Implementation Plan

> **Superseded on 2026-08-04:** This plan describes the retired parallel
> `Team`/`AgentProfile` configuration model and second scheduler. Do not execute
> it for new work. Use the four `2026-08-04-multi-agent-*` plans, which make the
> Agent Bundle the only configuration source and project real Session execution
> into Run/Task/Attempt records.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** 在 Omnigent 本地 fork 中落地一个以固定 Coordinator 为入口、支持多仓 worktree、自动编排、Durable Ledger、Web Team Builder 和飞书机器人工作台的团队多 Agent Harness。

**Architecture:** Omnigent 保存 Run、Task、Attempt、Session、Dependency、Event、Artifact、Approval 和 Notification 的唯一事实状态。Coordinator 是唯一的业务编排入口，Worker 通过 Parent Inbox 回传结构化结果；Lark Adapter 只负责 Device Flow、WebSocket/API 事件、卡片动作和通知，并将所有入站动作提交给 Coordinator/确定性状态机。Workspace Bundle 保留需求目录下同级独立 Git 仓库，通过 Attempt 级 worktree lease 提供隔离执行。

**Tech Stack:** Python 3.12、现有 Omnigent server/entities/db/Alembic、FastAPI 路由、SQLite/PostgreSQL 兼容存储、React/React Router/TanStack Query、飞书 PersonalAgent Device Flow、飞书 WebSocket 与 Interactive Card。

---

## 设计边界和成功标准

- 飞书只提供任务入口、通知和必要审批；Run/Task/Attempt/依赖/日志/事件/产物全部以 Omnigent Ledger 为准。
- 一个 Team 绑定一个固定 Coordinator；Worker 的飞书配对只改变显示身份和通知目标，任何入站 \`@Worker\` 都必须转交 Coordinator。
- Worker 完成事件自动进入 Coordinator Parent Inbox；无 Hard Block 时不等待人工评论。
- 一个 Workspace 是需求目录，不要求自身为 Git 仓库；\`.workbench-workspace.json\` 中 \`expertProjects\` 对应多个同级独立仓库。
- 工作区切换只影响当前话题后续新 Run；运行中的 Run 的 \`workspace_id\` 不变。
- Bot Surface 初始化必须幂等，应用级菜单不可用时降级为常驻“Omnigent 工作台”交互卡片，并记录 \`partial\`。
- 所有写操作都要有测试，所有状态迁移和飞书回调都要有幂等校验。

## 文件清单（先锁定边界）

后端新增领域/编排文件：

~~~text
omnigent/omnigent/entities/team.py
omnigent/omnigent/entities/run.py
omnigent/omnigent/entities/workspace_bundle.py
omnigent/omnigent/entities/feishu.py
omnigent/omnigent/teams/__init__.py
omnigent/omnigent/teams/events.py
omnigent/omnigent/teams/states.py
omnigent/omnigent/teams/reducer.py
omnigent/omnigent/teams/idempotency.py
omnigent/omnigent/teams/coordinator.py
omnigent/omnigent/teams/scheduler.py
omnigent/omnigent/teams/router.py
omnigent/omnigent/integrations/lark/__init__.py
omnigent/omnigent/integrations/lark/device_flow.py
omnigent/omnigent/integrations/lark/credentials.py
omnigent/omnigent/integrations/lark/protocol.py
omnigent/omnigent/integrations/lark/adapter.py
omnigent/omnigent/integrations/lark/router.py
omnigent/omnigent/integrations/lark/cards.py
omnigent/omnigent/integrations/lark/surface.py
omnigent/omnigent/server/routes/teams.py
omnigent/omnigent/server/routes/workspaces.py
omnigent/omnigent/server/routes/feishu.py
omnigent/omnigent/server/schemas/team.py
omnigent/omnigent/server/schemas/workspace.py
omnigent/omnigent/db/migrations/versions/za1b2c3d4e5f_add_team_harness_tables.py
~~~

前端新增/修改文件：

~~~text
omnigent/web/src/lib/teamsApi.ts
omnigent/web/src/lib/workspacesApi.ts
omnigent/web/src/lib/feishuApi.ts
omnigent/web/src/hooks/useTeams.ts
omnigent/web/src/hooks/useWorkspaces.ts
omnigent/web/src/hooks/useFeishuInstall.ts
omnigent/web/src/hooks/useTeamRuns.ts
omnigent/web/src/pages/TeamsPage.tsx
omnigent/web/src/pages/TeamDetailPage.tsx
omnigent/web/src/pages/RunInspectorPage.tsx
omnigent/web/src/components/teams/TeamForm.tsx
omnigent/web/src/components/teams/AgentProfileList.tsx
omnigent/web/src/components/teams/FeishuPairingPanel.tsx
omnigent/web/src/components/teams/BotSurfacePanel.tsx
omnigent/web/src/components/runs/RunInspector.tsx
omnigent/web/src/App.tsx
omnigent/web/src/shell/AppShell.tsx
~~~

测试文件按现有布局新增：

~~~text
omnigent/tests/entities/test_team_entities.py
omnigent/tests/teams/test_reducer.py
omnigent/tests/teams/test_coordinator_scheduler.py
omnigent/tests/teams/test_workspace_registry.py
omnigent/tests/teams/test_multirepo_worktree_lease.py
omnigent/tests/integrations/lark/test_device_flow.py
omnigent/tests/integrations/lark/test_adapter_router.py
omnigent/tests/integrations/lark/test_surface.py
omnigent/tests/server/test_team_routes.py
omnigent/tests/server/test_feishu_routes.py
omnigent/web/src/pages/TeamsPage.test.tsx
omnigent/web/src/pages/TeamDetailPage.test.tsx
omnigent/web/src/pages/RunInspectorPage.test.tsx
~~~

## Task 0: 建立实现分支并保护基线

**Files:** 无源码改动；只创建 Git 分支。

- [ ] **Step 1: 记录当前工作树和基线提交**

~~~bash
git -C /Users/zzzz/Documents/multi-agent/omnigent status --short
git -C /Users/zzzz/Documents/multi-agent/omnigent rev-parse HEAD
~~~

Expected: 只看到用户已有的六组未提交修改，HEAD 为已确认设计提交链。

- [ ] **Step 2: 创建实现分支**

~~~bash
git -C /Users/zzzz/Documents/multi-agent/omnigent switch -c feat/feishu-team-harness
~~~

Expected: 当前分支为 \`feat/feishu-team-harness\`，用户已有修改保持原样。

- [ ] **Step 3: 将用户已有修改登记为不属于本计划的基线**

~~~bash
git -C /Users/zzzz/Documents/multi-agent/omnigent diff --name-only
~~~

实现期间每次提交只允许显式添加本计划文件；禁止使用 \`git add -A\`。

## Task 1: 建立 Team/Run/Workspace/Feishu 领域实体

**Files:**
- Create: \`omnigent/omnigent/entities/team.py\`
- Create: \`omnigent/omnigent/entities/run.py\`
- Create: \`omnigent/omnigent/entities/workspace_bundle.py\`
- Create: \`omnigent/omnigent/entities/feishu.py\`
- Modify: \`omnigent/omnigent/entities/__init__.py\`
- Test: \`omnigent/tests/entities/test_team_entities.py\`

- [ ] **Step 1: 写实体边界测试**

~~~python
def test_run_captures_immutable_workspace_and_team():
    run = Run.new(team_id="team-1", workspace_id="ws-1", source="feishu")
    assert run.team_id == "team-1"
    assert run.workspace_id == "ws-1"
    assert run.status == RunStatus.QUEUED
    assert run.source == "feishu"

def test_agent_pairing_has_no_secret():
    pairing = FeishuPairing(display_name="后端 Worker", notify=("failure",))
    assert pairing.secret is None
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
cd /Users/zzzz/Documents/multi-agent/omnigent
.venv/bin/pytest tests/entities/test_team_entities.py -q
~~~

Expected: FAIL，因为新实体和状态枚举尚未定义。

- [ ] **Step 3: 实现最小实体和值对象**

实现 \`Team\`、\`AgentProfile\`、\`Run\`、\`Task\`、\`Attempt\`、\`WorkspaceBundle\`、\`RepositorySpec\`、\`FeishuInstallation\`、\`FeishuPairing\` 和状态枚举；\`Run.workspace_id\` 只在构造时赋值，\`FeishuPairing\` 只保存显示配置和 installation 引用，不保存 App Secret。

- [ ] **Step 4: 运行测试确认通过**

~~~bash
.venv/bin/pytest tests/entities/test_team_entities.py -q
~~~

Expected: PASS。

- [ ] **Step 5: 提交实体变更**

~~~bash
git add omnigent/entities omnigent/tests/entities/test_team_entities.py
git commit -m "feat: add team harness domain entities"
~~~

## Task 2: 建立数据库表和迁移

**Files:**
- Modify: \`omnigent/omnigent/db/db_models.py\`
- Create: \`omnigent/omnigent/db/migrations/versions/za1b2c3d4e5f_add_team_harness_tables.py\`
- Test: \`omnigent/tests/db/test_team_harness_migration.py\`

- [ ] **Step 1: 写迁移结构测试**

~~~python
def test_team_harness_tables_exist_after_upgrade(db_engine):
    upgrade_to_head(db_engine)
    assert_table_names(db_engine, {
        "teams", "agent_profiles", "team_members", "workspace_bundles",
        "workspace_repositories", "runs", "run_tasks", "task_dependencies",
        "attempts", "harness_events", "artifacts", "feishu_installations",
        "feishu_notifications", "idempotency_keys",
    })
~~~

- [ ] **Step 2: 运行迁移测试确认失败**

~~~bash
.venv/bin/pytest tests/db/test_team_harness_migration.py -q
~~~

Expected: FAIL，表尚不存在。

- [ ] **Step 3: 添加最小可查询模型和 Alembic upgrade/downgrade**

所有表使用现有 workspace/account 主键风格；\`runs.workspace_id\`、\`attempts.workspace_lease_id\`、\`harness_events.event_id\`、\`idempotency_keys(scope,key)\` 建索引/唯一约束；敏感凭证字段只存加密密文。迁移必须可重复执行，downgrade 按外键依赖逆序删除。

- [ ] **Step 4: 验证 upgrade、downgrade 和现有迁移链**

~~~bash
.venv/bin/pytest tests/db/test_team_harness_migration.py -q
.venv/bin/python -m alembic -c omnigent/db/alembic.ini check
~~~

Expected: 两条命令 PASS，现有数据库迁移无漂移。

- [ ] **Step 5: 提交数据库变更**

~~~bash
git add omnigent/db/db_models.py omnigent/db/migrations/versions/za1b2c3d4e5f_add_team_harness_tables.py tests/db/test_team_harness_migration.py
git commit -m "feat: persist team harness state"
~~~

## Task 3: 实现 Durable Ledger、事件 reducer 和幂等键

**Files:**
- Create: \`omnigent/omnigent/teams/events.py\`
- Create: \`omnigent/omnigent/teams/states.py\`
- Create: \`omnigent/omnigent/teams/reducer.py\`
- Create: \`omnigent/omnigent/teams/idempotency.py\`
- Test: \`omnigent/tests/teams/test_reducer.py\`

- [ ] **Step 1: 写状态迁移和重复事件测试**

~~~python
def test_worker_completion_wakes_coordinator_once(ledger):
    event = WorkerCompleted(event_id="evt-1", task_id="task-1", attempt_id="a-1")
    ledger.append(event)
    ledger.append(event)
    reduce_all(ledger)
    assert ledger.task("task-1").status == TaskStatus.COMPLETED
    assert ledger.coordinator_wake_count("run-1") == 1

def test_invalid_cancel_transition_is_rejected(ledger):
    with pytest.raises(InvalidTransition):
        reduce_event(ledger, CancelRun(run_id="completed-run"))
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/teams/test_reducer.py -q
~~~

Expected: FAIL。

- [ ] **Step 3: 实现追加式 Ledger 和纯 reducer**

事件必须包含 \`event_id\`、\`run_id\`、\`actor_type\`、\`actor_id\`、\`occurred_at\`、\`payload\` 和 \`correlation_id\`。\`append\` 用唯一 \`(scope,event_id)\` 保证重复投递安全；reducer 只允许显式状态图；每次状态变更追加审计事件，不覆盖原始事件。

- [ ] **Step 4: 运行测试确认通过**

~~~bash
.venv/bin/pytest tests/teams/test_reducer.py -q
~~~

Expected: PASS。

- [ ] **Step 5: 提交 Ledger 变更**

~~~bash
git add omnigent/teams omnigent/tests/teams/test_reducer.py
git commit -m "feat: add durable harness ledger and reducer"
~~~

## Task 4: 实现 Workspace Registry 和多仓扫描

**Files:**
- Create: \`omnigent/omnigent/workspaces/__init__.py\`
- Create: \`omnigent/omnigent/workspaces/registry.py\`
- Create: \`omnigent/omnigent/workspaces/manifest.py\`
- Modify: \`omnigent/omnigent/server/routes/_workspace_validation.py\`
- Test: \`omnigent/tests/teams/test_workspace_registry.py\`

- [ ] **Step 1: 写真实目录兼容测试**

~~~python
def test_registry_keeps_sibling_git_repositories(tmp_path):
    root = fixture_workspace(tmp_path, repos=("planet", "ZZAftersale", "ass_api"))
    bundle = WorkspaceRegistry().scan(root)
    assert [repo.id for repo in bundle.repositories] == ["planet", "ZZAftersale", "ass_api"]
    assert bundle.root == root
    assert all(repo.root.parent == root for repo in bundle.repositories)
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/teams/test_workspace_registry.py -q
~~~

Expected: FAIL。

- [ ] **Step 3: 实现 manifest 解析和安全扫描**

读取 \`.workbench-workspace.json\` 的 \`expertProjects\`；当清单缺失时只扫描一级子目录中的 Git 根；拒绝路径穿越、非目录和嵌套仓库歧义；输出稳定排序的 \`RepositorySpec\`，保留启动/验证命令和权限信息，不复制或合并仓库。

- [ ] **Step 4: 运行测试确认通过并验证用户目录**

~~~bash
.venv/bin/pytest tests/teams/test_workspace_registry.py -q
.venv/bin/python -c 'from omnigent.workspaces.registry import WorkspaceRegistry; print(WorkspaceRegistry().scan("/Users/zzzz/workbench-projects/projects/二奢寄卖-清分后不支持判商家责任"))'
~~~

Expected: 测试 PASS；命令列出 \`planet\`、\`ZZAftersale\`、\`asc\`、\`ass_core_logic\`、\`kfassrepairdao\`、\`ass_api\` 等同级仓库。

- [ ] **Step 5: 提交 Registry 变更**

~~~bash
git add omnigent/workspaces omnigent/server/routes/_workspace_validation.py tests/teams/test_workspace_registry.py
git commit -m "feat: support multi-repository workspace bundles"
~~~

## Task 5: 实现 Attempt 级 worktree lease

**Files:**
- Create: \`omnigent/omnigent/workspaces/worktree_lease.py\`
- Modify: \`omnigent/omnigent/server/routes/_host_worktree.py\`
- Test: \`omnigent/tests/teams/test_multirepo_worktree_lease.py\`

- [ ] **Step 1: 写并行 lease 测试**

~~~python
def test_two_attempts_get_distinct_worktrees_for_same_repo(repo):
    first = lease_for_attempt(repo, "attempt-1")
    second = lease_for_attempt(repo, "attempt-2")
    assert first.path != second.path
    assert first.branch != second.branch
    assert git_status_clean(first.path)
    assert git_status_clean(second.path)
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/teams/test_multirepo_worktree_lease.py -q
~~~

Expected: FAIL。

- [ ] **Step 3: 实现创建、回收和崩溃恢复**

每个可写 Attempt 为每个需要修改的仓库创建 \`git worktree add --detach\` 或命名分支；lease 表记录 host、repo、attempt、path、owner、状态和 heartbeat；创建使用事务/文件锁避免同一目录竞争，回收前校验 owner，过期 lease 由 reconciler 标记并安全删除。

- [ ] **Step 4: 运行测试确认通过**

~~~bash
.venv/bin/pytest tests/teams/test_multirepo_worktree_lease.py -q
~~~

Expected: PASS，包含同仓库并行、多个同级仓库和重复回收场景。

- [ ] **Step 5: 提交 worktree 变更**

~~~bash
git add omnigent/workspaces/worktree_lease.py omnigent/server/routes/_host_worktree.py tests/teams/test_multirepo_worktree_lease.py
git commit -m "feat: isolate attempts with multi-repo worktree leases"
~~~

## Task 6: 实现 Team/Workspace API 和 Coordinator 生命周期

**Files:**
- Create: \`omnigent/omnigent/server/schemas/team.py\`
- Create: \`omnigent/omnigent/server/schemas/workspace.py\`
- Create: \`omnigent/omnigent/server/routes/teams.py\`
- Create: \`omnigent/omnigent/server/routes/workspaces.py\`
- Modify: \`omnigent/omnigent/server/app.py\`
- Test: \`omnigent/tests/server/test_team_routes.py\`

- [ ] **Step 1: 写 API 合同测试**

~~~python
def test_create_team_requires_coordinator(client):
    response = client.post("/v1/teams", json={"name": "dev", "workers": []})
    assert response.status_code == 422

def test_workspace_switch_does_not_mutate_running_run(client, run):
    response = client.post("/v1/workspaces/ws-2/select", json={"thread_id": "thread-1"})
    assert response.status_code == 200
    assert client.get(f"/v1/runs/{run.id}").json()["workspace_id"] == "ws-1"
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/server/test_team_routes.py -q
~~~

Expected: FAIL，因为路由尚未注册。

- [ ] **Step 3: 实现 Team Builder 所需 CRUD 和 workspace 选择 API**

提供 \`GET/POST/PATCH /v1/teams\`、\`GET/PATCH /v1/teams/{id}\`、\`GET/POST /v1/workspaces\`、\`POST /v1/workspaces/{id}/select\`、\`GET /v1/teams/{id}/runs\`。创建 Run 时复制 thread 默认 workspace，运行后拒绝改变；schema 返回能力标签、并发上限、Harness、Coordinator、Worker Profiles、Feishu Pairing 和 Surface 状态。

- [ ] **Step 4: 注册路由并运行测试**

~~~bash
.venv/bin/pytest tests/server/test_team_routes.py -q
~~~

Expected: PASS。

- [ ] **Step 5: 提交 API 变更**

~~~bash
git add omnigent/server/schemas/team.py omnigent/server/schemas/workspace.py omnigent/server/routes/teams.py omnigent/server/routes/workspaces.py omnigent/server/app.py tests/server/test_team_routes.py
git commit -m "feat: expose team and workspace APIs"
~~~

## Task 7: 实现 Coordinator、DAG 调度和 Parent Inbox 自动唤醒

**Files:**
- Create: \`omnigent/omnigent/teams/coordinator.py\`
- Create: \`omnigent/omnigent/teams/scheduler.py\`
- Create: \`omnigent/omnigent/teams/router.py\`
- Test: \`omnigent/tests/teams/test_coordinator_scheduler.py\`

- [ ] **Step 1: 写自动推进和阶段路由测试**

~~~python
def test_completed_worker_unblocks_review_without_human_comment(coordinator, ledger):
    coordinator.start_run(run_id="run-1")
    coordinator.on_worker_completed("run-1", "task-1", "attempt-1")
    assert ledger.task("review-task").status == TaskStatus.READY
    assert coordinator.wake_count("run-1") == 1

def test_same_issue_can_use_different_profiles_by_stage(coordinator):
    assert coordinator.choose_profile(stage="implementation").id == "backend"
    assert coordinator.choose_profile(stage="review").id == "reviewer"
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/teams/test_coordinator_scheduler.py -q
~~~

Expected: FAIL。

- [ ] **Step 3: 实现确定性 DAG 调度器**

Coordinator 将模型输出限制为经过 schema 校验的计划变更：创建 Task、依赖、阶段和所需能力；scheduler 仅在依赖完成、配额可用且 lease 成功时启动 Attempt；Parent Inbox 事件触发一次 coordinator wake，自动执行 review、retry、merge 或 hard block；并发上限按 Agent Profile 和 Team 分别计数。

- [ ] **Step 4: 实现失败诊断和通知事件**

每次 Attempt 失败必须产生包含 \`failure_code\`、退出码、最后工具调用、日志引用、重试次数和建议动作的 \`AttemptFailed\`；通知策略按 Coordinator/Worker pairing 过滤，但不改变状态机。

- [ ] **Step 5: 运行测试确认通过**

~~~bash
.venv/bin/pytest tests/teams/test_coordinator_scheduler.py -q
~~~

Expected: PASS，覆盖并行任务、阶段切换、失败重试、Hard Block 和重复完成事件。

- [ ] **Step 6: 提交编排变更**

~~~bash
git add omnigent/teams/coordinator.py omnigent/teams/scheduler.py omnigent/teams/router.py tests/teams/test_coordinator_scheduler.py
git commit -m "feat: automate coordinator scheduling and parent inbox wakeups"
~~~

## Task 8: 实现飞书 PersonalAgent Device Flow 和凭证存储

**Files:**
- Create: \`omnigent/omnigent/integrations/lark/device_flow.py\`
- Create: \`omnigent/omnigent/integrations/lark/credentials.py\`
- Create: \`omnigent/omnigent/server/routes/feishu.py\`
- Test: \`omnigent/tests/integrations/lark/test_device_flow.py\`
- Test: \`omnigent/tests/server/test_feishu_routes.py\`

- [ ] **Step 1: 写 Device Flow 测试**

~~~python
def test_begin_install_returns_qr_and_polling_session(fake_lark, client):
    fake_lark.begin_result = {"device_code": "d-1", "verification_uri_complete": "https://lark/scan"}
    response = client.post("/v1/teams/team-1/feishu/install/begin")
    assert response.status_code == 200
    assert response.json()["qr_url"] == "https://lark/scan"

def test_successful_poll_encrypts_secret_and_starts_installation(fake_lark, keyring, client):
    fake_lark.poll_result = {"client_id": "app", "client_secret": "secret", "open_id": "ou-1"}
    response = client.get("/v1/teams/team-1/feishu/install/s-1/status")
    assert response.json()["status"] == "ready"
    assert keyring.contains_ciphertext("secret")
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/integrations/lark/test_device_flow.py tests/server/test_feishu_routes.py -q
~~~

Expected: FAIL。

- [ ] **Step 3: 实现 begin/poll/status/disconnect**

按 Multica 已验证的 PersonalAgent Device Flow 调用 \`accounts.feishu.cn/oauth/v1/app/registration\`；二维码只返回一次性 \`verification_uri_complete\`；后台 polling 遵循服务端 interval/expiry；成功后调用 Bot Info、加密保存 secret、写 installation 和安装者 open_id；超时、拒绝和网络错误统一返回可诊断状态。

- [ ] **Step 4: 运行测试确认通过**

~~~bash
.venv/bin/pytest tests/integrations/lark/test_device_flow.py tests/server/test_feishu_routes.py -q
~~~

Expected: PASS，且响应和日志中不出现明文 App Secret。

- [ ] **Step 5: 提交 Device Flow 变更**

~~~bash
git add omnigent/integrations/lark/device_flow.py omnigent/integrations/lark/credentials.py omnigent/server/routes/feishu.py tests/integrations/lark/test_device_flow.py tests/server/test_feishu_routes.py
git commit -m "feat: add feishu personal agent installation flow"
~~~

## Task 9: 实现 Lark Adapter、事件去重和 Coordinator 路由

**Files:**
- Create: \`omnigent/omnigent/integrations/lark/protocol.py\`
- Create: \`omnigent/omnigent/integrations/lark/adapter.py\`
- Create: \`omnigent/omnigent/integrations/lark/router.py\`
- Modify: \`omnigent/omnigent/server/app.py\`
- Test: \`omnigent/tests/integrations/lark/test_adapter_router.py\`

- [ ] **Step 1: 写文本、@Worker、按钮和重连测试**

~~~python
def test_worker_mention_is_routed_to_coordinator(adapter, coordinator):
    adapter.receive(message(chat_id="c", text="@backend 修复接口"))
    assert coordinator.received[-1].text == "@backend 修复接口"
    assert coordinator.received[-1].actor == "coordinator"

def test_card_action_is_idempotent(adapter, fake_card_action):
    first = adapter.receive(fake_card_action(action_id="retry", nonce="n-1"))
    second = adapter.receive(fake_card_action(action_id="retry", nonce="n-1"))
    assert first.result == second.result
    assert adapter.coordinator.retry_count == 1
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/integrations/lark/test_adapter_router.py -q
~~~

Expected: FAIL。

- [ ] **Step 3: 实现 Adapter**

解码 \`im.message.receive_v1\` 和 \`card.action.trigger\`；按 \`chat_id/thread_id\` 查 Team/Coordinator/default workspace；校验签名、成员权限、Team 绑定、状态迁移和 nonce；处理 WebSocket 心跳、断线重连、发送重试和卡片 \`update_multi=true\`；任何 Worker 入站都转换为 Coordinator \`RunRequest\`。

- [ ] **Step 4: 运行测试确认通过**

~~~bash
.venv/bin/pytest tests/integrations/lark/test_adapter_router.py -q
~~~

Expected: PASS，覆盖重复事件、未知话题、无权限按钮和断线恢复。

- [ ] **Step 5: 提交 Adapter 变更**

~~~bash
git add omnigent/integrations/lark omnigent/server/app.py tests/integrations/lark/test_adapter_router.py
git commit -m "feat: route feishu events through coordinator"
~~~

## Task 10: 实现扫码后幂等 Bot Surface Provisioner

**Files:**
- Create: \`omnigent/omnigent/integrations/lark/cards.py\`
- Create: \`omnigent/omnigent/integrations/lark/surface.py\`
- Modify: \`omnigent/omnigent/server/routes/feishu.py\`
- Test: \`omnigent/tests/integrations/lark/test_surface.py\`

- [ ] **Step 1: 写 Surface 能力探测、降级和幂等测试**

~~~python
def test_surface_falls_back_to_persistent_card_when_menu_is_unavailable(fake_lark, provisioner):
    fake_lark.menu_supported = False
    result = provisioner.ensure("installation-1")
    assert result.status == "partial"
    assert result.surface_type == "persistent_card"

def test_surface_provision_is_idempotent(fake_lark, provisioner):
    provisioner.ensure("installation-1")
    provisioner.ensure("installation-1")
    assert fake_lark.created_surface_count == 1
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
.venv/bin/pytest tests/integrations/lark/test_surface.py -q
~~~

Expected: FAIL。

- [ ] **Step 3: 实现固定工作台卡片和菜单初始化**

默认入口为团队工作、全部会话、代码变更、设置；快捷动作包括新建任务、当前任务、查看 Worker、查看失败、切换工作区、查看成品、帮助；上下文选择器包括工作区、仓库/服务、本地 Host、执行模式。动作 payload 只包含服务端签名的 \`action_id/run_id/task_id/attempt_id/nonce\`。

- [ ] **Step 4: 实现安装状态持久化**

写入 \`surface_profile_id\`、\`surface_version\`、\`provision_status\`、\`provision_error\`、\`last_provisioned_at\` 和 Ledger 事件；菜单权限不足时记录 \`partial\` 并更新常驻卡片；重复扫码、进程重启和手动重新初始化复用已存在 surface。

- [ ] **Step 5: 运行测试确认通过**

~~~bash
.venv/bin/pytest tests/integrations/lark/test_surface.py -q
~~~

Expected: PASS。

- [ ] **Step 6: 提交 Surface 变更**

~~~bash
git add omnigent/integrations/lark/cards.py omnigent/integrations/lark/surface.py omnigent/server/routes/feishu.py tests/integrations/lark/test_surface.py
git commit -m "feat: provision idempotent feishu bot workspace"
~~~

## Task 11: 实现 Web API client、hooks 和 Teams 一级导航

**Files:**
- Create: \`omnigent/web/src/lib/teamsApi.ts\`
- Create: \`omnigent/web/src/lib/workspacesApi.ts\`
- Create: \`omnigent/web/src/lib/feishuApi.ts\`
- Create: \`omnigent/web/src/hooks/useTeams.ts\`
- Create: \`omnigent/web/src/hooks/useWorkspaces.ts\`
- Create: \`omnigent/web/src/hooks/useFeishuInstall.ts\`
- Modify: \`omnigent/web/src/App.tsx\`
- Modify: \`omnigent/web/src/shell/AppShell.tsx\`
- Test: \`omnigent/web/src/pages/TeamsPage.test.tsx\`

- [ ] **Step 1: 写路由和 API hook 测试**

~~~tsx
it("renders Teams navigation and loads teams", async () => {
  render(<App />)
  expect(await screen.findByRole("link", { name: "Teams" })).toBeVisible()
})
~~~

- [ ] **Step 2: 运行前端测试确认失败**

~~~bash
pnpm --dir web test --run src/pages/TeamsPage.test.tsx
~~~

Expected: FAIL，因为 Teams 路由和 hook 尚不存在。

- [ ] **Step 3: 实现 API client 和缓存策略**

使用现有 \`authenticatedFetch\`；query key 分别为 \`teams\`、\`workspaces\`、\`team-runs\`、\`feishu-install\`; mutation 成功后只失效相关 key，不清空会话缓存；错误对象保留后端 \`failure_code\`、\`provision_error\` 和 request id。

- [ ] **Step 4: 在 AppShell 增加一级 Teams 导航和路由**

增加 \`/teams\`、\`/teams/:teamId\`、\`/runs/:runId\`，保持现有 Chat/Inbox/Tasks/Settings 路由；导航项使用现有图标和 active 样式，不改动无关侧边栏布局。

- [ ] **Step 5: 运行前端测试确认通过**

~~~bash
pnpm --dir web test --run src/pages/TeamsPage.test.tsx
pnpm --dir web lint
~~~

Expected: PASS，lint 无新增错误。

- [ ] **Step 6: 提交前端基础变更**

~~~bash
git add web/src/lib/teamsApi.ts web/src/lib/workspacesApi.ts web/src/lib/feishuApi.ts web/src/hooks/useTeams.ts web/src/hooks/useWorkspaces.ts web/src/hooks/useFeishuInstall.ts web/src/App.tsx web/src/shell/AppShell.tsx web/src/pages/TeamsPage.test.tsx
git commit -m "feat: add teams navigation and API hooks"
~~~

## Task 12: 实现 Team Builder、Agent Pairing 和 Bot Surface 配置页

**Files:**
- Create: \`omnigent/web/src/pages/TeamsPage.tsx\`
- Create: \`omnigent/web/src/pages/TeamDetailPage.tsx\`
- Create: \`omnigent/web/src/components/teams/TeamForm.tsx\`
- Create: \`omnigent/web/src/components/teams/AgentProfileList.tsx\`
- Create: \`omnigent/web/src/components/teams/FeishuPairingPanel.tsx\`
- Create: \`omnigent/web/src/components/teams/BotSurfacePanel.tsx\`
- Test: \`omnigent/web/src/pages/TeamDetailPage.test.tsx\`

- [ ] **Step 1: 写 Team Builder 交互测试**

~~~tsx
it("edits coordinator, workers, workspace and pairing", async () => {
  render(<TeamDetailPage />)
  await userEvent.selectOptions(screen.getByLabelText("Coordinator"), "polly")
  await userEvent.click(screen.getByRole("button", { name: "连接飞书" }))
  expect(screen.getByText("扫码绑定飞书智能体/机器人")).toBeVisible()
})
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
pnpm --dir web test --run src/pages/TeamDetailPage.test.tsx
~~~

Expected: FAIL。

- [ ] **Step 3: 实现 Team Builder 表单**

可视化编辑 Coordinator、Worker Profiles、Harness、能力标签、每 Profile 并发上限、Workspace Bundle、执行模式、Agent 飞书显示身份、头像/通知级别及固定动作显示/隐藏；保存前校验必须有且仅有一个 Coordinator、Profile id 唯一且并发上限为正整数。

- [ ] **Step 4: 实现扫码绑定和 Surface 状态展示**

点击“连接飞书”调用 begin API，展示二维码、过期倒计时和 polling 状态；安装成功显示 bot 名称、open_id、surface 状态；\`partial\` 明确列出菜单不可用和卡片降级原因；提供幂等“重新初始化工作台”按钮。

- [ ] **Step 5: 运行测试确认通过**

~~~bash
pnpm --dir web test --run src/pages/TeamDetailPage.test.tsx
pnpm --dir web lint
~~~

Expected: PASS。

- [ ] **Step 6: 提交 Team Builder 变更**

~~~bash
git add web/src/pages/TeamsPage.tsx web/src/pages/TeamDetailPage.tsx web/src/components/teams web/src/pages/TeamDetailPage.test.tsx
git commit -m "feat: add visual team and feishu pairing builder"
~~~

## Task 13: 实现 Run Inspector、失败诊断和评测视图

**Files:**
- Create: \`omnigent/web/src/hooks/useTeamRuns.ts\`
- Create: \`omnigent/web/src/pages/RunInspectorPage.tsx\`
- Create: \`omnigent/web/src/components/runs/RunInspector.tsx\`
- Test: \`omnigent/web/src/pages/RunInspectorPage.test.tsx\`

- [ ] **Step 1: 写可追溯性展示测试**

~~~tsx
it("shows task DAG, attempt logs and failure reason", async () => {
  render(<RunInspectorPage />)
  expect(await screen.findByText("failure_code: TEST_COMMAND_EXIT_1")).toBeVisible()
  expect(screen.getByText("Coordinator Parent Inbox")).toBeVisible()
  expect(screen.getByText("workspace: luxury-resale-settlement")).toBeVisible()
})
~~~

- [ ] **Step 2: 运行测试确认失败**

~~~bash
pnpm --dir web test --run src/pages/RunInspectorPage.test.tsx
~~~

Expected: FAIL。

- [ ] **Step 3: 实现 Inspector**

展示 Run 状态、不可变 workspace、Task DAG、每个 Attempt 的 Agent Profile、worktree、阶段、开始/结束时间、工具调用、stdout/stderr、failure_code、重试建议、Parent Inbox 事件、提交和产物链接；实时更新只追加事件，不覆盖历史。

- [ ] **Step 4: 增加评测摘要**

按 Run 计算完成率、首次成功率、重试次数、人工审批次数、平均阶段耗时、并行利用率、Token/资源消耗和最终交付状态；评测数据从 Ledger 聚合，不从飞书消息反推。

- [ ] **Step 5: 运行测试确认通过**

~~~bash
pnpm --dir web test --run src/pages/RunInspectorPage.test.tsx
pnpm --dir web lint
~~~

Expected: PASS。

- [ ] **Step 6: 提交 Inspector 变更**

~~~bash
git add web/src/hooks/useTeamRuns.ts web/src/pages/RunInspectorPage.tsx web/src/components/runs/RunInspector.tsx web/src/pages/RunInspectorPage.test.tsx
git commit -m "feat: add run trace and evaluation inspector"
~~~

## Task 14: 端到端验收、恢复和运行手册

**Files:**
- Create: \`omnigent/tests/e2e/test_feishu_team_harness.py\`
- Create: \`omnigent/tests/fixtures/fake_lark.py\`
- Create: \`omnigent/tests/fixtures/fake_host.py\`
- Create: \`omnigent/docs/feishu-team-harness-runbook.md\`

- [ ] **Step 1: 写端到端验收场景**

~~~python
def test_feishu_run_executes_parallel_multi_repo_attempts_and_notifies(fake_lark, fake_host, client):
    install_team_with_workers(client, fake_lark)
    run = send_feishu_text(fake_lark, "修复清分后不支持判商家责任", workspace="luxury-resale-settlement")
    assert wait_until(lambda: run_status(run) == "completed")
    assert max_parallel_attempts(run) >= 2
    assert sibling_repositories_unchanged(fake_host)
    assert fake_lark.has_notification("final", run.id)
~~~

- [ ] **Step 2: 运行端到端测试确认失败**

~~~bash
.venv/bin/pytest tests/e2e/test_feishu_team_harness.py -q
~~~

Expected: FAIL，直到所有组件接线完成。

- [ ] **Step 3: 注入恢复和网络故障场景**

覆盖 Device Flow 超时、WebSocket 断线、重复卡片回调、Worker 进程失败、Coordinator 重启、过期 lease 回收、菜单 API 不可用、Run 中途切换 workspace 被拒绝等场景；每种失败都要求在 Inspector 和飞书通知中给出 \`failure_code\`、上下文和下一步动作。

- [ ] **Step 4: 运行后端、前端和端到端全套验证**

~~~bash
.venv/bin/pytest tests -q
pnpm --dir web test --run
pnpm --dir web lint
.venv/bin/python -m alembic -c omnigent/db/alembic.ini check
git diff --check
~~~

Expected: 测试、lint、迁移检查和 diff 检查均 PASS；若环境缺少 \`pre-commit\`，只记录该命令不可用，不把它报告为通过。

- [ ] **Step 5: 编写本地运行手册**

记录数据库迁移、Omnigent server/host 启动、Web UI 地址、飞书环境变量/密钥注入、扫码安装、Team 创建、工作区注册、多仓验证、常见 \`failure_code\` 排查、日志位置、重连和 Surface 重新初始化步骤；明确禁止把 App Secret 写进 Agent Profile 或仓库。

- [ ] **Step 6: 提交验收和手册**

~~~bash
git add tests/e2e tests/fixtures docs/feishu-team-harness-runbook.md
git commit -m "test: verify feishu team harness end to end"
~~~

## Final branch handoff

- [ ] 确认实现分支只包含本计划提交和用户明确要求的改动：

~~~bash
git -C /Users/zzzz/Documents/multi-agent/omnigent status --short
git -C /Users/zzzz/Documents/multi-agent/omnigent log --oneline --decorate -12
~~~

- [ ] 在 \`feat/feishu-team-harness\` 完成验收后，向用户展示提交列表和测试结果；得到明确合并指令后再执行：

~~~bash
git switch feat/feishu-team-harness-design
git merge --no-ff feat/feishu-team-harness -m "merge: add feishu team harness"
~~~

- [ ] 合并前后都不得暂存或覆盖以下用户已有文件：\`codex_native_app_server.py\`、\`inner/codex_executor.py\`、\`runtime/workflow.py\` 以及对应测试文件。
