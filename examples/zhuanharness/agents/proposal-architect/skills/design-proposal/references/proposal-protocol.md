# Proposal Protocol

## 输入门禁

输入至少包含 `task_id`、`requirement_id`、`change_id`、`workspace_root`、`attempt_root`、Requirement Manifest、research artifact refs、decision refs、现行 spec refs 和真实 `hook_context`。Requirement 状态必须 `READY`；所有用于方案的事实必须有 Artifact 引用。

Proposal Architect 可以做可逆的本地技术选择，但必须在 design 的 Assumptions 中写清依据和影响。涉及业务语义、范围、兼容承诺、授权或不可逆行为时，不自行选择，返回 Decision Gap。

## Artifact 图

- `proposal.md`：问题、目标、范围/非目标、受影响能力/仓库、风险、Acceptance ID；
- `design.md`：当前代码 anchors、组件/数据流、API/message/data/config/state contract、兼容性、失败处理、发布回滚、可观测性、测试 seams；
- `specs/<capability>/spec.md`：ADDED/MODIFIED/REMOVED/RENAMED Requirements，每个 Requirement 描述含 MUST/SHALL 且至少一个 Given/When/Then Scenario；
- `tasks.md`：纵向 Delivery Task、`blocked_by`、Acceptance IDs、仓库、完整 write scope、Worker Packets、TDD policy、测试 seam 和 required checks；
- `artifacts/proposal/proposal-manifest.json`：机器契约与所有文件摘要。

不要重复生成 `techDesign/tech-spec.md`。旧 change 已有该文件时只作为输入读取并保留，不继续写镜像。

## 并行与 TDD

前后端 Packet 可并行的必要条件：共享契约为 `FROZEN`、完整 write scopes 不重叠、共同 blocker 已集成。TDD 决策顺序：用户明确选择 > 仓库政策 > 任务风险与快速独立 seam > AI 默认。模式为 `required|recommended|skip`，skip 必须有理由；TDD 不是独立 Worker。

## 输出 Manifest

至少包含 `change_id`、`status`、`requirements`、`acceptance_ids`、`tasks`、`shared_contracts`、`artifacts`、`validation`。状态只允许 `READY|NEEDS_RESEARCH|NEEDS_USER_DECISION|INVALID`。READY 时每个 Acceptance ID 必须被 spec Scenario 与至少一个 Task 覆盖，每个 Task 的 blocker 必须存在且无环；并行 FE/BE Packet 必须引用已冻结 contract。
