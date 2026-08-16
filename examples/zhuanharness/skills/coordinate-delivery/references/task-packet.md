# Task Packet 与 Result Envelope

## Task Packet

每个 Worker 只接收一个自包含任务：

```json
{
  "task_id": "REQ-7:BE-1",
  "requirement_id": "REQ-7",
  "worker": "backend-implementer",
  "objective": "实现已冻结接口的服务端逻辑",
  "inputs": ["artifacts/contracts/order-api.yaml"],
  "deliverables": ["artifacts/BE-1/report.md"],
  "acceptance": ["unit tests pass"],
  "workspace_root": "/workspace/request",
  "attempt_root": "/runtime/attempt-1",
  "task_mode": "worktree-write",
  "worktree_root": "/runtime/attempt-1",
  "write_scope": ["server/**"],
  "attempt": 1,
  "hook_context": {
    "status": "DEFERRED",
    "attempt_root": "/runtime/attempt-1",
    "reason": "Hooks are scheduled for a later milestone"
  },
  "parallel_group": "order-page",
  "shared_contract": {
    "status": "FROZEN",
    "artifact": "artifacts/contracts/order-api.yaml"
  }
}
```

`inputs` 只列当前任务需要的 Artifact 或文件；禁止要求 Worker 重读整段会话。`task_mode` 只允许 `read`、`control-plane-write` 或 `worktree-write`。所有任务都传 `workspace_root`、当前 `attempt_root` 和 `hook_context`。

Requirement Analyst、Research Engineer、Proposal Architect 使用 `control-plane-write`：

- `workspace_root` 与 Ominigent Child Session 的 workspace 都是共享 Workspace 根；
- 只写 Packet 指定的根层 `zhuanspec/changes/**`；
- 不创建产品 Worktree，不向 `todo-app/zhuanspec` 写控制面副本，不 commit、不创建 handoff ref。

实现、集成或测试 author 使用 `worktree-write`，必须同时传：

- `workspace_root`：原始研发空间，只读共享需求、ZhuanSpec 和项目知识；
- `worktree_root`：Ominigent 为当前 Attempt 分配的可写 Worktree；
- `write_scope`：当前 Worker 在 Worktree 内允许修改的完整范围。

`hook_context.status` 当前使用 `DEFERRED`，必须给出 `reason`，且 `attempt_root` 与任务包一致；该状态只表示 Hooks 延期，不表示已采集过程事件。未来 Hooks 建好后切换为 `READY`，届时必须同时确认项目 Settings、Harness Hook 物化和唯一 `event_shard`。

`write_scope` 是职责契约，不是 OS 安全沙箱。Worktree Worker 不得在 Skill 内自行创建 Worktree，也不得写原始 `workspace_root`。前端与后端处于同一 `parallel_group` 时，`shared_contract.status` 必须为 `FROZEN` 且有 Artifact。

## Result Envelope

```json
{
  "task_id": "REQ-7:BE-1",
  "attempt": 1,
  "status": "DONE",
  "work_type": "implementation",
  "attempt_started_at": "2026-08-12T10:00:00+08:00",
  "artifact": "artifacts/BE-1/report.md",
  "summary": "接口实现与单元测试完成",
  "evidence": [
    {"kind": "commit", "ref": "abc123", "attempt": 1, "produced_at": "2026-08-12T10:08:00+08:00"},
    {"kind": "test", "command": "npm test", "exit_code": 0, "summary": "42 passed", "attempt": 1, "produced_at": "2026-08-12T10:10:00+08:00"}
  ],
  "questions": []
}
```

状态只允许：

- `DONE`：验收完成且证据齐全；
- `DONE_WITH_CONCERNS`：已交付，但存在不阻塞的明确风险；
- `NEEDS_CONTEXT`：缺少可由 Coordinator 或 Research Engineer 补充的事实；
- `BLOCKED`：缺少外部授权、环境变化或不可替代的人类决策。

`summary` 最长 240 个字符。完整正文、代码 diff、截图和日志必须写入 Artifact。`DONE` 与 `DONE_WITH_CONCERNS` 必须提供 Artifact、`work_type`、Attempt 启动时间和新鲜 Evidence。每条 Evidence 必须绑定相同 Attempt，并且产生时间不得早于 Attempt；测试证据必须含实际命令、`exit_code=0` 和摘要。代码实现还必须提供 Commit 或等价变更引用。

## Preflight / Harness Precheck

进入专职阶段前先产生 `harness-precheck` Artifact，至少记录 `run_id`、`status`、`blocked_stage`，required/available/missing 的 Worker 与 Skill 集合，以及 `hooks_mode`。

- `DEFERRED`：必须记录 `hooks_deferred_reason` 和真实缺口；Hook 缺失不改变 READY/BLOCKED，Worker/Skill 缺失仍阻塞。
- `ENFORCED`：必须记录 `hook_installer: "zhuanspec init --harness"`、项目 Settings、Attempt bootstrap 与 required/available/missing Hook 事件；任一缺失即阻塞。

`missing_*` 必须严格等于 required 减 available。用 `scripts/validate-contract.py harness-precheck <json-file>` 校验。

## 产物登记

当前 Artifact Registry 是 ZhuanSpec 控制面索引，位于 `zhuanspec/changes/<change-id>/harness/runs/<run-id>/`，至少记录：`artifact_id`、`run_id`、`task_id`、`type`、`path`、`content_hash`、`created_at` 和 `producer_attempt`。消息中的路径不是完成证据；Coordinator 必须确认目标可读取且与登记哈希一致。Envelope 的 `attempt` 必须与登记的 `producer_attempt` 一致。

## Ominigent 运行时映射

| 动作 | Ominigent 能力 | 约束 |
|---|---|---|
| 首次派发已声明 Worker | `sys_session_send(agent, title, message)` | Worker 必须位于 Bundle 的 `tools.agents` 白名单 |
| 继续已有 Worker | `sys_session_send(session_id, message)` | 只传短 Envelope 或稳定 Artifact 引用 |
| 恢复 Session 树 | `sys_session_list`、`sys_session_get_info`、`sys_session_get_history` | 聊天摘要只用于解释 |
| 接收异步结果 | `sys_read_inbox` | 不忙轮询，不依赖 Worker 长消息 |
| 取消 Runaway | `sys_cancel_task` | 先确认停止或记录取消状态，再创建新 Attempt |
| 关闭废弃子 Session | `sys_session_close` | 仅在 Bundle 已开放派发能力时可用 |

`async: true` 只开放异步调用与 Inbox，不会开放 `sys_session_send`。只有 `tools.agents` 或 `spawn: true` 才会注册派发工具；zhuanharness 使用固定角色白名单，不使用任意 `spawn`。

Ominigent 是 Run、Root/Worker Session、Attempt、Worktree Lease 与取消状态的事实源。Coordinator 不直接写 Ominigent 数据库；自有 Task Packet、Decision Ledger、Artifact Registry 和交付摘要由 Coordinator 单写到 `zhuanspec/changes/<change-id>/harness/runs/<run-id>/`。该 Artifact Registry 是当前阶段的 ZhuanSpec 控制面索引，不冒充 Ominigent `artifacts` 表。

Artifact Record 使用以下结构，并以 `python3 scripts/validate-contract.py artifact-record <json-file>` 校验：

```json
{
  "artifact_id": "ART-1",
  "run_id": "RUN-1",
  "task_id": "REQ-7:R-1",
  "type": "research-report",
  "path": "zhuanspec/changes/x/artifacts/R-1/report.md",
  "content_hash": "64位小写SHA-256",
  "created_at": "2026-08-12T10:01:00+08:00",
  "producer_attempt": 1
}
```
