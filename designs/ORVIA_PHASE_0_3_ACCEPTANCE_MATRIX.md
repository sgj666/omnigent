# Orvia Phase 0–3 验收矩阵

> 核验日期：2026-08-07
> 唯一开发基线：`team-harness@94f349a4e644e4ec6c518128b5002af7b9c2f765`
> 唯一开发目录：`/Users/zzzz/Documents/multi-agent/omnigent/.worktrees/team-harness`
> 浏览器验收地址：`http://127.0.0.1:5173`
> 后端地址：`http://127.0.0.1:6777`

## 证据等级

- **已证明**：代码、自动化门禁和所需右侧浏览器路径均有直接证据。
- **部分证明**：实现和自动化证据存在，但计划要求的某个真实环境或浏览器场景尚缺。
- **待外部条件**：必须获得新的安全凭据或真实鉴权环境，不能在产品代码中增加调试入口绕过。
- **按计划禁用**：能力有安全边界，但本阶段明确不开放写操作。

## Phase 0：稳定地基

| 要求 | 状态 | 当前证据 | 剩余事项 |
| --- | --- | --- | --- |
| Automations canonical 路由迁移 | 已证明 | `/automations` 为唯一自动化集合页；Phase 2 已按计划让 `/tasks` 成为 Task Board；standalone/embed 路由测试位于 `web/src/App.automations.test.tsx` | 无 |
| Typed navigation registry | 已证明 | `web/src/lib/navigation.ts`、`navigation.test.ts`；侧栏真实浏览器显示任务、自动化、项目、收件箱、多智能体、Skills、运行时、用量 | 无 |
| 集合页 UI 原语 | 已证明 | `web/src/components/collection/` 被多个集合页复用；完整前端回归通过 | 无 |
| Project 查询与数据收口 | 已证明 | `projectQueries.ts`、Project/Session owner isolation 与删除清引用测试；右侧浏览器可从 Projects 进入详情 | 无 |
| Session 创建原子绑定 Project | 已证明 | Session API 和 `test_sessions_project_membership.py` 覆盖；不依赖前端二次 patch | 无 |
| Task/TaskRun/Inbox 双端契约 | 已证明 | `omnigent/work_lifecycle.py`、`web/src/lib/workLifecycle.ts` 及双端契约测试 | 无 |
| Inbox 投送策略与事件事实分离 | 已证明 | progress、action、completed、failed 分类；普通 progress 不制造全部 unread | 无 |

## Phase 1：只读管理面

| 要求 | 状态 | 当前证据 | 剩余事项 |
| --- | --- | --- | --- |
| Projects 集合、搜索、排序、摘要 | 已证明 | `/projects`；排序写入 `sort` URL；真实页面显示 Session 与 Artifact 摘要，并可进入详情 | 无 |
| Usage 集合与可信数据缺口 | 已证明 | `/usage`、`usageApi.ts`、`test_usage_report.py`；估算与无样本场景不伪造数值 | 无 |
| Runtime 集合与只读诊断 | 已证明 | `/runtime` 与 `/runtime/:id`；Runtime 页面测试和正常浏览器路径 | 无 |
| Multi-Agent 集合增强 | 已证明 | 继续使用唯一 `/multi-agents`；右侧浏览器真实显示 `debby-copy`、`debby`、`polly`，以及 Workers、Skills、Harness、版本、校验和飞书状态 | 无；禁止新增 `/agents` 产品路由 |
| Automations 信息增强 | 已证明 | 搜索状态写入 `q`/`status` URL；浏览器刷新恢复 `q=Orvia`；组件测试覆盖状态筛选 | 当前真实数据无 paused Automation，因此 paused 的真实页面证据尚无样本，但实现与测试已证明 |
| 五集合页加载/空/错误态 | 已证明 | 各页面组件测试覆盖，完整前端回归通过 | 无 |
| 五集合页无权限态 | 已证明 | 使用独立临时数据库启动真实 header-auth 后端；Projects、Usage、Runtime、Multi-Agent、Automations 均通过右侧浏览器收到真实 401 并显示专用中文权限态 | 无；未增加 debug 产品入口 |
| URL 恢复关键筛选 | 已证明 | Projects、Automations、Tasks 等 URL 状态测试；Projects/Automations 已做真实刷新验证 | 无 |

## Phase 2：Task 工作闭环

| 要求 | 状态 | 当前证据 | 剩余事项 |
| --- | --- | --- | --- |
| `work_items` / `work_item_runs` / `inbox_items` 数据模型 | 已证明 | additive migrations `zg`–`zj`；临时 SQLite 完整 upgrade/downgrade/upgrade 通过 | 真实数据库只允许 upgrade，不执行破坏性 downgrade |
| Task Board/List、创建和筛选 | 已证明 | `/tasks` Board/List、URL 筛选、拖拽乐观锁测试；右侧浏览器真实创建多条验收任务 | 无 |
| Task 详情与 TaskRun 审计 | 已证明 | `/tasks/:id`、Run 历史、retry/cancel、Session 回链；关联后端测试通过 | 无 |
| waiting → action → resume → success | 已证明 | 既有右侧浏览器闭环验收任务与 Inbox/Task 回链；持久 waiting/terminal 投影测试 | 无 |
| 完成/失败/等待持久投送 | 已证明 | 收件箱四分组；右侧浏览器可见完成、失败和需处理项目 | 无 |
| 已读/未读与批量已读 | 已证明 | API/组件测试；右侧浏览器真实执行“标为已读 → 标为未读 → 恢复” | 无 |
| WebSocket 实时 + API 断线恢复 | 已证明 | 两个真实浏览器标签已读/未读双向同步；后端停止并重启后，未刷新观察端自动收到新完成事件；最终刷新数量稳定 | 无 |
| TaskRun 丢失投影恢复 | 已证明 | Inbox GET read-repair；真实历史缺口自动补齐；重复刷新 dedupe 行仍为 1；历史 Task 完成通知已存在时仍会继续修复同 Task 的缺失 terminal Run 投影 | 无 |
| Task 完成投影恢复与稳定去重 | 已证明 | 持久 `completion_id`；历史 version 键兼容；77 项后端关联回归通过 | 无 |
| 完成后普通编辑不重复通知 | 已证明 | 右侧浏览器：完成后优先级编辑，刷新前后通知数稳定；数据库唯一 dedupe 行 | 无 |
| 重新打开后再次完成产生新事件 | 已证明 | 右侧浏览器：版本 3→4→5→6，两次合法完成对应两个不同 `completion_id`，之后编辑不产生第三条 | 无 |
| 现有真实数据库升级 | 已证明 | 升级前备份；`zi7d8e9f0a1b` → `zj8e9f0a1b2c`；`PRAGMA integrity_check = ok`；服务重启后健康 200 | 备份保留于 `~/.omnigent/chat.db.pre-zj8e9f0a1b2c-20260807-0028.bak` |
| Project 删除不误删 Task 历史 | 已证明 | Project 删除仅清引用，Task/TaskRun 保留；后端测试覆盖 | 无 |

## Phase 3：Skills、Artifacts 与分析

| 要求 | 状态 | 当前证据 | 剩余事项 |
| --- | --- | --- | --- |
| Git-backed Skills Inventory | 部分证明 | Reader、SHA 快照、离线 fallback、目录解析和诊断测试通过；右侧浏览器验证 `/skills` 未配置、只读、空清单和安全同步状态 | GitLab 真实 remote 尚未完成安全只读 smoke |
| Reader / Publisher 权限隔离 | 已证明 | 浏览/同步只注入 Reader；真实远端测试代码不存在写操作 | 无 |
| Draft workspace | 已证明 | 本地 draft 创建、编辑、丢弃路径与测试 | 无 |
| Validate | 已证明 | 结构、元数据、引用和 secret 检测；后端测试通过 | 无 |
| Dry Run 与 remote HEAD 漂移保护 | 已证明 | 临时 bare remote 测试覆盖 diff 与 ref drift；真实仓库不写 | 无 |
| Publish | 按计划禁用 | UI 明确禁用，普通 Inventory/Validate/Dry Run 可使用 | 只有安全评审和用户独立明确确认后才能另行开放 |
| Advanced Usage | 已证明 | Task/Run/Project/Agent/Runtime/Skill 归因与数据缺口；`test_usage_report.py` | 无 |
| Project Artifacts | 已证明 | 引用 FileStore，不复制文件；Projects 摘要与详情回链 TaskRun；真实页面显示 artifact | 无 |
| Agent Activity | 已证明 | Runs、成功/失败/等待原因、Skills/Projects 回链；删除 Agent 后历史显示“已删除智能体 · id” | 无 |
| GitLab 真实只读 smoke | 待外部条件 | 只执行过未认证 `git ls-remote`，因无凭据失败；远端没有任何改变 | 需要通过 Secret/Environment 注入新的、仅 `read_repository` 权限 `ORVIA_SKILLS_GIT_TOKEN`；不得把 token 粘贴到聊天或命令参数 |

## 当前门禁结果

- 后端关联与迁移：`77 passed`，仅一条第三方弃用 warning。
- 前端类型检查：`tsc -b` 通过。
- 前端 lint：`oxlint --deny-warnings .` 通过。
- 前端完整回归：`309 passed / 1 skipped` 测试文件；`5140 passed / 3 expected fail / 1 skipped` 测试。
- Python lint：本轮修改文件 `ruff check` 通过。
- 补丁完整性：`git diff --check` 通过。
- 本地服务：`5173` 前端和 `6777` 后端；后端健康检查 `200`。

## 尚不能宣称完成的事项

1. 通过安全环境变量获得新的只读 GitLab 凭据后，比较 smoke 前后 remote refs 并读取目标 `skills` 目录；全程禁止写操作。
2. 真实数据库 downgrade 会删除 Phase 2 新数据，只能宣称结构可回滚，不能宣称新功能数据无损回滚。
