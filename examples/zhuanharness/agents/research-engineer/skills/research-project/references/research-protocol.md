# Research Protocol

## 输入

Research Packet 至少包含：`task_id`、`research_id`、`requirement_id`、`change_id`、`workspace_root`、`attempt_root`、`question`、`acceptance_ids`、`artifact_refs`、`output_artifact` 和真实 `hook_context`。候选代码不在原工作区时额外传 `candidate_root` 与完整 `candidate_ref`。

先使用 `load-project-context`，coverage 根据问题选 `cross-stack|frontend|backend|test`。然后从 HTTP/RPC/MQ/job/UI route 等最小外部 seam 进入，依次检查业务决策、数据读写、配置、下游副作用和测试。调查范围扩大到新仓库前，必须说明它如何影响原问题。

## 结论模型

每个 finding 包含稳定 `F-*` ID、`statement`、`kind`、`confidence`、`source_refs`、`code_anchors`、`affects` 和 `verification`：

- `source_fact`：当前源码/配置/运行证据直接观察；
- `test_assertion`：当前测试明确断言；
- `knowledge_claim`：来自需求/知识/历史资料，尚需或已经过代码核验；
- `inference`：证据支持但未直接证明，不能关闭关键事实缺口。

`code_anchors` 使用 `repository:path:line`。实现相关的 `source_fact` 必须至少一个 anchor；知识结论必须通过 `verification=verified|contradicted|stale|unresolved` 显示与当前代码的关系。

## 输出

JSON Artifact 至少包含：

```json
{
  "task_id": "T-R-1",
  "research_id": "R-1",
  "status": "ANSWERED",
  "question": "当前商责拦截入口在哪里？",
  "findings": [],
  "conflicts": [],
  "unknowns": [],
  "decision_gaps": [],
  "repositories_checked": [],
  "artifacts": {"json": ".../R-1.json", "report": ".../R-1.md"}
}
```

状态只允许 `ANSWERED|PARTIAL|BLOCKED_EVIDENCE`。`ANSWERED` 不得有会改变答案的 unresolved unknown；业务选择只能进入 `decision_gaps`，由 Coordinator 路由。Markdown 报告按“答案、证据、影响表、冲突、未知、决策缺口”组织，不复制检索日志。
