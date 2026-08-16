# 前端实施契约

Task Packet 每个仓库必须给出 `run_base_sha`、`launch_head_sha`、`materialize_sha`、`expected_base_sha`、`owned_paths` 和预分配 `handoff_ref`。共享 API/schema/事件必须为 `FROZEN`，否则前后端不能并行猜字段。

正式 handoff 至少包含：状态、任务与 Acceptance IDs、完整 SHA、不可变 ref、父子关系、变更路径、clean flag、检查命令与持久日志锚点、TDD 证据引用和剩余风险。物理 Attempt 分支、未提交目录、短 SHA、mutable branch 或聊天中的“完成”都不是交付物。

允许状态：`READY_FOR_INTEGRATION`、`NO_CHANGE`、`BLOCKED_BASE_MISMATCH`、`BLOCKED_SCOPE`、`HANDOFF_REF_CONFLICT`、`FAILED_TEST`、`FAILED_IMPLEMENTATION`、`RECOVERY_REQUIRED`。
