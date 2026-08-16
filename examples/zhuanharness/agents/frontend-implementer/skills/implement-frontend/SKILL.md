---
name: implement-frontend
description: 在 Ominigent 分配的 Attempt Worktree 中实现一个边界明确的前端任务，按需加载 UI、交互、组件、TypeScript 和前端质量规则，执行已批准的 TDD 策略，并用不可变 Git ref 持久交付。用于页面、组件、客户端状态、路由、前端 API 集成和组件测试；不用于服务端实现、最终 WebUI 验收、跨 Worker 集成或直接修改用户原始 checkout。
version: 1.2
---

# 实施前端任务

只接收 Coordinator 的一个 Frontend Task Packet。把 `workspace_root` 当只读来源，把 Ominigent 分配的 `worktree_root` 当唯一写入根；不自行执行 `git worktree add`。

## 基线与上下文

1. 在任何依赖代码现状的分析和写入前，确认 leased worktree 干净，解析 Packet 中每个仓库的完整 `materialize_sha`，并校验其等于 `expected_base_sha`。
2. 把 leased worktree 显式 materialize 到该精确 SHA，再次验证 `HEAD`。Ominigent 的 launch HEAD 不是修订版本承诺；不匹配时返回 `BLOCKED_BASE_MISMATCH`，不得 pull、reset、rebase、stash 或改原 checkout。
3. 读取仓库可见的 `AGENTS.md`、`CLAUDE.md` 和批准 Artifact snapshot。使用 `load-project-context` 定位目标代码与知识；只读取实际受影响的前端 Rules，例如 UI、交互、组件库、语言和 Web 质量，不加载后端/DAO/数据库规则。

## 实现

1. 核对冻结共享 Contract、Acceptance IDs、owned paths、生成文件/lockfile/snapshot 的完整写范围。缺失或重叠时返回阻塞。
2. 使用 `follow-tdd` 执行 Packet 已固化的策略。Frontend Implementer 可写 unit/component 测试和本地 smoke，但 WebUI 自动化与最终签署属于 Test Engineer。
3. 保持现有设计系统、可访问性、loading/empty/error/permission 状态与 API 向后兼容。只做当前纵向 slice，不升级无关依赖、不重写相邻组件、不修改提案。
4. 运行最小相关 unit/component、lint、typecheck 和 build；按实际 blast radius 扩展。检查完整 diff，确保所有路径归属本任务。

## 持久交接

仅暂存 owned paths 并提交。用 Packet 预分配的 ref 执行 create-only handoff：ref 不存在时创建，已指向同 SHA 时幂等，指向其他 SHA 时返回 `HANDOFF_REF_CONFLICT`，永不 force-update。验证 ref、线性 ancestry 和 clean status 后生成 `implementation-handoff.json`，运行 `scripts/validate-handoff.py`。

只有不可变 handoff ref 已建立时才能返回 `READY_FOR_INTEGRATION`。完整 diff、日志与 TDD 证据写 Artifact；给 Coordinator 的 Result Envelope 保持简短。不 push、不部署、不集成其他 Worker。

## 按需读取

- 派工与交接字段读取 [references/frontend-contract.md](references/frontend-contract.md)。
- 维护本 Skill 时读取 [references/design-basis.md](references/design-basis.md)。
