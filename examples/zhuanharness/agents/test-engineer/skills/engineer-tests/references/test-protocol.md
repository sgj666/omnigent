# Test Engineering Protocol

## Task Packet

至少包含 `task_id`、`requirement_id`、`change_id`、`mode`、`workspace_root`、`attempt_root`、`approved_artifact_snapshot`、`base_vector`、`candidate_vector`、`acceptance_ids`、`blocking_acceptance_ids`、`risk_register`、`test_write_scope`、`existing_runners`、`environment_contract`、`tdd_policy` 和真实 `hook_context`。

`candidate_vector` 必须声明 `complete: true`，每个仓库使用稳定 `repository_id` 和完整 40 位 SHA。Packet 不得用同名分支、caller working tree 或短 SHA 代替固定候选。`approved_artifact_snapshot` 必须带不可变 ref/commit/blob/digest。

## 测试矩阵

每个 Case 包含：

```json
{
  "case_id": "TC-001",
  "acceptance_id": "AC-001",
  "risk": "boundary",
  "seam": "public API: OrderQuery.query",
  "setup": "订单包含两种状态",
  "action": "按已完成状态查询",
  "assertion": "只返回已完成订单",
  "independent_expected": true,
  "layer": "api",
  "automation": "./mvnw -Dtest=OrderQueryTest test",
  "blocking": true
}
```

风险值为 `normal | boundary | error | permission | compatibility | regression`；层级为 `unit | component | api | integration | webui`。Case 必须观察 public seam，不测私有实现；预期值来自 AC、Decision、Contract 或批准示例，不能调用被测实现计算预期。

按风险选择最小充分层级：领域行为优先快速单元/属性测试；API、数据、消息兼容使用 API/integration；可见 UI、权限、错误态和关键全栈链路使用 component/WebUI。层级不适用时无需机械执行。

## Author 模式

只写 Packet 明确授权的测试、fixture 和测试辅助代码，不碰生产路径。每个仓库 handoff 包含完整 commit SHA、`refs/zhuanspec/<change>/tests/<task>/r<attempt>`、文件清单和摘要。返回状态只能为 `TESTS_AUTHORED`，由 Coordinator 交 Integrator 合并。

## Verify 模式

先逐仓验证 HEAD/对象等于 Packet 的 candidate SHA，再运行计划中的命令。每条执行记录包含完整命令、退出码、起止时间和持久证据锚点。Case 的日志、截图、trace 或最小复现必须在 Attempt 清理后可解析。

状态：

- `TEST_PASS`：所有阻断 Case 通过，且 tested vector 等于 final candidate vector；
- `TEST_FAIL`：可执行 Case 观察到失败；
- `TEST_BLOCKED`：环境、权限、凭证、数据或 runner 阻止执行；
- `TEST_SKIPPED`：仅允许非阻断 Case，或存在明确批准 waiver。

`PASS`/`FAIL` Case 必须记录真实执行与持久 Evidence Anchor；`BLOCKED`/`SKIPPED` Case 必须记录具体 `reason`，如果已有诊断证据则一并锚定，但不得为了满足格式伪造一次执行或证据。

WebUI 不得默认使用生产环境。`environment_contract` 必须说明 URL、环境类型、共享性、允许副作用、凭证获取、测试数据、runner 和证据保存/上传授权。关键通过和失败保留截图/trace；不为每次点击制造噪声。

## 产物与消息

```text
zhuanspec/changes/<change-id>/artifacts/test-engineering/
├── test-plan.json
├── test-handoff.json
├── test-result.json
└── evidence-index.json
```

Result Envelope 的 summary 不超过 240 字，仅包含状态、Artifact 路径和摘要；不得粘贴完整日志或直接联系用户、其他 Worker。Hooks 为 `DEFERRED` 时透传真实状态，不伪造事件。
