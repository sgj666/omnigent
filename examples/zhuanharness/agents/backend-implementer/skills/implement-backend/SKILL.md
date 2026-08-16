---
name: implement-backend
description: 在 Ominigent 分配的 Attempt Worktree 中实现一个边界明确的后端任务，按需加载 API、领域、数据、安全和服务端规则，执行已批准的 TDD 策略，并用不可变 Git ref 持久交付。用于服务、API、RPC/MQ、领域逻辑、DAO、数据库或后端配置任务；不用于前端实现、最终验收、跨 Worker 集成或直接修改用户原始 checkout。
version: 1.2
---

# 实施后端任务

只接收 Coordinator 的一个 Backend Task Packet。把 `workspace_root` 当只读来源，把 Ominigent 分配的 `worktree_root` 当唯一写入根；不自行执行 `git worktree add`。

## 基线与上下文

1. 在任何依赖代码现状的分析和写入前，确认 leased worktree 干净，解析 Packet 中每个仓库的完整 `materialize_sha`，并校验其等于 `expected_base_sha`。
2. 把 leased worktree 显式 materialize 到该精确 SHA，再次验证 `HEAD`。Ominigent 的 launch HEAD 不是修订版本承诺；不匹配时返回 `BLOCKED_BASE_MISMATCH`，不得 pull、reset、rebase、stash 或改原 checkout。
3. 读取仓库可见的 `AGENTS.md`、`CLAUDE.md` 和批准 Artifact snapshot。使用 `load-project-context` 定位目标代码与知识；只读取实际受影响的 API、领域、DAO/数据库、安全、配置和服务端 Rules，不加载 UI/组件规则。

## 实现

1. 核对冻结共享 Contract、Acceptance IDs、owned paths 以及 schema、生成代码、lockfile、registry 的完整写范围。缺失或重叠时返回阻塞。
2. 从真实外部入口追踪业务决策和持久化/下游副作用，保持 API/RPC/消息/数据/配置兼容性、事务、幂等、失败与灰度语义。
3. 使用 `follow-tdd` 执行 Packet 已固化的策略。围绕公开 API/领域 seam 做纵向 RED/GREEN；只 mock 系统边界，不 mock 内部实现。
4. 只做当前 slice，不添加推测性抽象、不改无关依赖、不重构相邻代码、不修改提案。运行最小相关 unit/integration、lint/typecheck/compile/package，检查完整 diff 和路径所有权。

## 持久交接

仅暂存 owned paths 并提交。用 Packet 预分配的 ref 执行 create-only handoff：ref 不存在时创建，已指向同 SHA 时幂等，指向其他 SHA 时返回 `HANDOFF_REF_CONFLICT`，永不 force-update。验证 ref、线性 ancestry 和 clean status 后生成 `implementation-handoff.json`，运行 `scripts/validate-handoff.py`。

只有不可变 handoff ref 已建立时才能返回 `READY_FOR_INTEGRATION`。完整 diff、日志与 TDD 证据写 Artifact；给 Coordinator 的 Result Envelope 保持简短。不 push、不部署、不集成其他 Worker。

## 按需读取

- 派工与交接字段读取 [references/backend-contract.md](references/backend-contract.md)。
- 维护本 Skill 时读取 [references/design-basis.md](references/design-basis.md)。
