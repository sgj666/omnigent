# 设计依据与裁剪记录

本文件只供维护、评审和回归设计时读取。普通协调运行不加载，避免把历史分析反复占用上下文。

## 版本与证据

| 来源 | 版本或快照 | 本地证据 |
|---|---|---|
| ZhuanSpec 历史工作区 | `zhuanspec init` 生成资产，2026-08-12 审计 | `/Users/zzzz/workbench-projects/projects/二奢寄卖-清分后不支持判商家责任/.claude/commands/zhuanspec/`、`.claude/agents/`、`zhuanspec/` |
| Polly | 用户提供的本地快照，2026-08-12 审计 | `/Users/zzzz/Downloads/polly/config.yaml`、`skills/fanout`、`skills/investigate`、`skills/cross-review` |
| Matt Pocock Engineering Skills | commit `84fdeffd12f2ee307994d1eb6feb48173b6e0502` | `references/mattpocock-skills/skills/productivity/grilling`、`skills/engineering/{research,to-spec,to-tickets,implement,code-review}` |
| Superpowers | version `6.2.0`，commit `44c9b2d6e889982ac18c27d05a19fefe335194e1` | `references/superpowers/skills/{dispatching-parallel-agents,using-git-worktrees,verification-before-completion}` |
| OpenSpec | commit `e50bd0983dc8dc48250e3181f36e28450542f2ab` | `references/openspec` 的 Artifact Graph、propose/apply/verify 工作流 |
| Ominigent | 当前工作区源码，2026-08-12 审计 | `omnigent/agent_bundles/service.py`、`omnigent/spec/parser.py`、Run/Attempt Worktree 实现 |

上游项目为 MIT 时，只有被实际改写进正文的通用流程思想被内化；本 Skill 不复制完整上游文件。来源 commit 用于后续差异审计。

## ZhuanSpec 历史逻辑

### 保留

- `proposal.md`、`design.md`、`specs/**`、`tasks.md` 是提案事实基座。
- 开始设计或代码定位前加载项目知识；保留 ProjectWiki、`zhuanspec/knowledge`、项目级 Hooks、纠偏记录和知识闭环。
- 实施、测试、审查均产出正式文件，不能只靠聊天声称完成。

### 舍弃

- 不再用六个 Commands 要求用户手动切阶段。
- 不逐阶段重复询问测试来源、依赖状态和是否继续；只在决策真的影响行为、范围、兼容、风险或授权时询问。
- 不转发 Worker 的完整进度块和长报告，不让模型主动调用 Skill 来模拟无感过程采集。
- 不允许多个 Worker 读改写同一个聚合进度 JSON；Worker 只追加 Attempt 事件分片，聚合结果由 Projector 重建。

### 理由

历史资产本身有价值，问题集中在编排方式过重、上下文重复和人工门禁过密。Coordinator 应保留产物与证据，替换 Commands 驱动方式。

## Polly

### 保留

- Coordinator 是 Tech Lead，不是 Coder；实现、调查和审查交给专职 Worker。
- 异步派发后通过 Inbox 监督，不忙轮询。
- 实现者不能签署最终独立审查；Runaway 先取消再重派。
- 任务必须带明确目的、范围和验收契约。

### 舍弃

- 不按 Claude/Codex 等厂商划分研发职责，而按需求、研究、提案、前端、后端、测试、验证和审查划分。
- 不采用“每个实现者各开 PR、用户自行合并”的固定交付模型。
- Coordinator 不手工创建 Worktree；Ominigent 是 Worktree 生命周期 Owner。

### 理由

Polly 的通信和监督模式成熟，但其厂商路由、PR 交付与 zhuanharness 的多仓研发空间和角色分工不一致。

## Matt Pocock Engineering Skills

### 保留

- `grilling` 的 Decision Frontier：只处理前置决策已解决的问题，同一轮问题相互独立，并给出推荐答案与后果。
- `research` 的证据优先和短报告纪律。
- `to-spec` 的“提案只综合已有决定，不二次访谈、不为填模板发明需求”。
- `to-tickets` 的纵向交付切片和 blocker 关系。

### 舍弃

- 不“relentlessly”扩展不会影响验收、范围、兼容、风险或成本的分支。
- 不让 Worker 直接问用户、发布 Issue/Ticket、创建后台 Agent 或自动提交。

### 理由

保留决策图和交付切片，去掉对 Issue Tracker 和单 Agent 用户交互的假设，落实 Coordinator-only 通信。

## Superpowers

### 保留

- Fresh Context Task Packet、自包含范围和验收标准。
- 只有相互独立、写入范围不冲突的工作才能并行。
- 完成前必须运行新鲜验证，Agent 报告不能代替证据。

### 舍弃

- 不让 Skill 自己派生 Subagent、创建 Worktree 或完成分支合并。
- 不对所有简单任务强制完整 brainstorming 和逐段用户批准。

### 理由

Superpowers 的工程纪律有效，但其调度动作与 Ominigent 重叠；Skill 只保留判定和证据原则。

## OpenSpec

### 保留

- Artifact Graph 和产物状态闭包；WHY、WHAT、HOW、TASKS 各有唯一产物。
- 验证 Completeness、Correctness、Coherence 后才能完成。
- 对纯重构等情况允许按规则跳过不适用 Artifact，不伪造需求。

### 舍弃

- 不再运行一套 OpenSpec CLI 或 Provider Commands，不创建第二套目录。

### 理由

ZhuanSpec 已承载提案、知识、Hooks 和归档；OpenSpec 贡献产物图方法，不成为平行事实源。

## Ominigent

### 保留

- Coordinator 是 Bundle 根 Agent；Worker 位于 `agents/<worker>/`。
- `remote_skills` 按 Agent 配置物化，源码共仓不代表运行上下文共享。
- Run、Attempt、Inbox 和 Worktree Lease 是运行时事实源。
- 使用 `skills: none` 关闭当前机器的全局共享 Skill 继承；通过 `remote_skills` 物化进 Bundle 的专属 Skill 仍然可用。

### 舍弃

- 不在 Skill 中重写 Session、Inbox、Worktree 和 Agent Bundle 功能。
- 不把 Worktree 当作 Rules/Skills 隔离；Instructions 和 `remote_skills` 才负责上下文隔离。
- 不把全局 Skill 继承当作项目 Settings 或 Hooks 的承载机制；`skills: none` 在 Claude SDK 下会同时关闭 project setting sources，未来 `ENFORCED` Hooks 必须通过独立 Attempt-start adapter 物化和启用。
- 不把 Workspace Manifest 的 `startupCommands` 当作现成 bootstrap；当前运行链路只解析该字段，没有执行它。

### 理由

Harness 应是薄的组织协议层，避免和基座争夺生命周期所有权。

### Attempt Hooks 审计结论

Ominigent 会在 `<workspace>-worktrees/omnigent-attempt-<id>/` 下为每个声明的 Git 仓库创建 Worktree，并把 Runner CWD 设为 Attempt 根目录；当前没有把多仓工作区顶层 `.claude/`、`.codex/`、`AGENTS.md`、`CLAUDE.md` 或 `zhuanspec/` 物化到 Attempt 根目录的能力。因此未来新版 `zhuanspec init --harness` 仍需生成 Harness 控制面与物化清单，并提供 Worktree 创建后、Runner 启动前的薄 Attempt-start 接缝。该接缝属于 ZhuanSpec/Ominigent adapter，不属于 Coordinator Skill。当前按用户要求使用 `DEFERRED` 模式继续建设；切换到 `ENFORCED` 后缺失才阻塞。

## 设计亮点

1. **Decision Frontier 三分法**：已有证据由 Coordinator 回答，事实缺口给 Research Engineer，只有不可替代的决策问用户。
2. **Artifact-first 通信**：完整结果落盘，消息摘要最长 240 字，降低截断和上下文污染。
3. **双根 Task Packet**：同时传只读原工作空间和可写 Attempt Worktree，解决知识上下文与代码隔离不能兼得的问题。
4. **Contract-before-parallel**：共享接口、字段、消息和状态先冻结，再允许前后端并行。
5. **可恢复执行**：用 Run、`task_id + attempt`、Artifact Registry 和 Inbox 恢复，聊天摘要不是事实源。
6. **Hook 与 Skill 分层**：Skill 提供决策和协议，项目 Hook 自动采集所有 Worker 生命周期事件，Coordinator 只消费投影。
7. **并发安全事件分片**：每个 Attempt/Worker 只追加自己的 JSONL，Projector 归并 `progress.json` 与准确性结果。
