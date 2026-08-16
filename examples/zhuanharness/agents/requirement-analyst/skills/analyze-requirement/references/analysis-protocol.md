# Requirement Analysis Protocol

## 输入 Brief

至少包含 `task_id`、`requirement_id`、`change_id`、`workspace_root`、`attempt_root`、原始目标、已知范围、已有决策、输入 `artifact_refs` 和真实 `hook_context`。先用 `validate-brief.py` 校验。输入不完整时继续完成可确认部分，把剩余内容分类为 Issue；不要默默填补业务含义或代码事实。

分析前调用 `load-project-context`，使用 `coverage=authoritative-only` 和 `harness_stage=requirement-analysis`，把结果写入知识 Artifact。轻量检索仍无法回答的事实才生成 Research Request；需要跨仓、运行态或深度调用链调查时交后续 Research Engineer，不在本 Worker 内无限扩张检索。

## Issue 分类

| category | 含义 | 路由 |
|---|---|---|
| `FACT_GAP` | 可从知识、代码、配置、数据或运行证据查明 | Research Request → Coordinator → Research Engineer |
| `BUSINESS_DECISION` | 业务语义或产品行为需要选择 | User Decision → Coordinator |
| `SCOPE_CONFLICT` | 目标、范围或非目标互相冲突 | Coordinator 先用已有决策化解，否则 User Decision |
| `CONTRACT_RISK` | API、事件、字段、数据或兼容契约风险 | 标记风险；需要事实时同时建 Research Request |
| `ACCEPTANCE_GAP` | 结果不可观察或验收口径缺失 | 补 AC；确需产品选择时建 User Decision |
| `SECURITY_RISK` | 权限、隐私、资金、数据迁移或不可逆操作 | 标记后续 SecurityGate |
| `DEPENDENCY_RISK` | 外部系统、团队、环境或发布顺序依赖 | 标记依赖；未知状态建 Research Request |

User Decision 的 `kind` 只允许：`business_semantics`、`scope_choice`、`compatibility_tradeoff`、`authorization`、`irreversible_decision`。`FACT_GAP` 不得进入 User Decision。每个 User Decision 至少提供两个结构化选项，每个选项包含 `id`、`label` 和 `impact`，并通过 `recommended_option_id` 给出推荐；Coordinator 可以用已有决策闭环时不得再询问用户。

## 拆分方法

使用两种 `split_basis`：

- `business-capability`：一个可命名的用户/业务能力；
- `delivery-slice`：能端到端演示和验收的纵向切片。

不要使用 `technical-layer`。同一能力需要 FE 和 BE 时保留一个 Capability，后续 Proposal/Planner 再映射到不同 Worker。Capability 必须有稳定 `CAP-*` ID、目标、来源和至少一个 `AC-*`。

## Acceptance Criteria

每条 AC 只表达一个可观察结果，优先使用 `WHEN / THEN`，并记录来源。不要把“代码已完成”“接口正常”“测试通过”当业务 AC；应描述输入、行为、边界和结果。技术质量要求可以作为风险或后续任务验收补充。

## Manifest 结构

```json
{
  "requirement_id": "REQ-101",
  "status": "READY",
  "summary": "不超过 240 字符",
  "split_basis": "business-capability",
  "capabilities": [
    {
      "id": "CAP-1",
      "title": "订单状态筛选",
      "objective": "用户可按状态看到匹配订单",
      "acceptance_criteria": ["AC-1"],
      "source_refs": ["input:user-request"]
    }
  ],
  "acceptance_criteria": [
    {
      "id": "AC-1",
      "statement": "WHEN 用户选择已完成 THEN 列表只展示已完成订单",
      "observable": true,
      "source_refs": ["input:user-request"]
    }
  ],
  "issues": [],
  "research_requests": [],
  "user_decisions": [],
  "traceability": [
    {"source_ref": "input:user-request", "targets": ["CAP-1", "AC-1"]}
  ],
  "artifacts": {
    "review": "zhuanspec/changes/add-order-filter/artifacts/requirement-analysis/requirement-review.md",
    "manifest": "zhuanspec/changes/add-order-filter/artifacts/requirement-analysis/requirement-manifest.json"
  }
}
```

`research_requests` 和 `user_decisions` 用 `issue_id` 关联 Issue。所有 ID 在各自集合中唯一；Traceability target 必须指向存在的 Capability 或 AC。每个 Capability 与 AC 的每个 `source_ref` 都必须存在对应 Traceability link；`NEEDS_SCOPE_REWORK` 必须存在 `SCOPE_CONFLICT`。

## Review 文档

`requirement-review.md` 面向 Coordinator 阅读，依次写：结论、目标/范围/非目标、能力地图、AC、Issues、Research Requests、User Decisions、风险和追踪表。长证据只引用已有 Artifact，不复制全文。

## Result Envelope

返回状态使用 Coordinator 协议的 `DONE` 或 `DONE_WITH_CONCERNS`，并在 `summary` 中说明 Requirement Review 状态。`artifact` 指向 Review 文档，`evidence` 包含 Manifest 路径和 `validate-manifest.py` 退出码。不得把 Issues 或完整问题列表塞进消息，也不得直接联系用户或其他 Worker。
