# Integration Protocol

## Request

至少包含 `task_id`、`change_id`、`attempt_root`、`control_repository_id`、`base_vector`、`handoffs`、`task_order`、`artifact_snapshot`、`required_checks`、`integration_attempt`、`output_manifest` 和真实 `hook_context`。

`base_vector` 列出完整 Workspace 仓库集合：`repository_id`、完整 `base_sha`、`materialize_ref`。handoff 至少含 `task_id`、`repository_id`、`ref`、`output_sha`、`base_sha`、`commits`、`changed_paths`、`owned_paths`。所有 ref 必须为 `refs/zhuanspec/<change>/handoff/...`，integration ref 预分配为 `refs/zhuanspec/<change>/integration/r<attempt>`。

## 收敛不变量

- 每个 handoff `base_sha` 等于对应 base vector；输出是其后代且提交链线性；
- `changed_paths` 全部位于 `owned_paths`；同一批 handoff 的完整 write scope 不冲突；
- task_order 覆盖每个 handoff task 且无重复；
- 每个 integration ref 使用 create-only/expected-old guard，禁止 force update；
- 多仓 candidate 只有在控制仓 manifest 列出全部仓库、ref/SHA、输入 handoffs、artifact snapshot 且 `status=COMPLETE` 时成立。

## 失败

状态只允许 `INTEGRATED|INTEGRATION_CONFLICT|INTEGRATION_FAILED|BLOCKED_BASE_MISMATCH|INVALID_HANDOFF`。冲突必须返回 repository、files、task refs 和命令证据。跨仓发布中途失败时尽可能锚定 `INCOMPLETE` manifest，并使用新的 attempt 号重试；不得把成功半边报告为已集成。

## Result

包含 `change_id`、`status`、`base_vector`、`input_handoffs`、`candidate_vector`、`manifest`、`applied_commits`、`checks`、`conflicts`、`unchanged_repositories`。`INTEGRATED` 要求所有 checks `exit_code=0`，candidate vector 与 base vector 仓库集合完全相同，manifest 为 COMPLETE，且每个 changed repo 都有 integration ref。
