---
name: integrate-worktrees
description: 在独立 Ominigent Attempt Worktree 中验证并按任务 DAG 收敛前后端等 Worker 的不可变 handoff refs，运行跨包检查并发布可复现的多仓 candidate vector 与 COMPLETE manifest。用于 Integrator 汇合并行实现或测试提交；不用于创建 Worktree、解决业务语义冲突、修改产品行为、推送或合并用户分支。
version: 1.2
---

# 集成 Worktree 产物

Integrator 是确定性收敛者，不是第三个 Implementer。

## 流程

1. 接收 [references/integration-protocol.md](references/integration-protocol.md) 定义的 Packet，运行 `python3 scripts/validate-integration.py request <packet.json>`。Worktree 由 Ominigent 分配，本 Skill 不运行 `git worktree add`。
2. 在 leased Attempt 中逐仓验证 clean、完整 base SHA、handoff ref 可解析、祖先关系、线性提交和 owned paths。先把每仓 HEAD 精确物化到声明 base；不匹配则 `BLOCKED_BASE_MISMATCH`，不得 reset/rebase 猜修。
3. 按 Task DAG、Task ID、Packet commit 顺序应用 handoff。出现文本或语义冲突时立即中止并返回冲突证据；不得选择 ours/theirs 或编辑业务代码。
4. 运行 Packet 声明的跨包 compile/typecheck/smoke checks。全部通过后，使用 create-only guard 发布每仓 integration ref，并在控制仓发布 `status: COMPLETE` 的 vector manifest。
5. 重新解析 manifest 与全部 refs，确认 clean、完整仓库集合及未改仓库 base 不变；运行 `validate-integration.py result` 后返回短 Result Envelope。

## 边界

- 只应用已验证提交并生成集成 refs/manifest；不修改业务语义、提案、测试内容或知识库。
- 不直接联系用户或其他 Worker，不自行派生 Worker；冲突由 Coordinator 路由回拥有者。
- 不 push、不建/合 PR/CR、不部署、不清理 handoff 或 integration refs。
- 单仓成功、多仓失败仍是整体失败；没有 COMPLETE manifest 的 refs 集合不是 candidate vector。

维护本 Skill 时读取 [references/design-basis.md](references/design-basis.md)；普通运行不要加载设计历史。
