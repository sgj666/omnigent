# Independent Review Protocol

## Review Packet

至少包含 `task_id`、`requirement_id`、`change_id`、`base_vector`、`tested_vector`、`verified_vector`、`reviewed_vector`、`final_delivery_vector`、批准 Artifact snapshot、Standards snapshot、commit list/diff commands、Test/Verifier 持久报告、批准 waivers 和真实 `hook_context`。

所有向量必须 `complete: true`，逐仓使用稳定 `repository_id` 和完整 40 位 SHA。批准/规则快照至少带 immutable ref、commit、blob path 和 SHA-256。Reviewer 使用 `git diff/show <sha>` 读取对象；每个仓库记录 `diff_checked: true` 和 `diff_non_empty`，预期有改动时必须为真。禁止 checkout 分支后读取可能变化的工作树。

## 四个独立轴

| axis | 核心问题 |
|---|---|
| `SPEC` | 是否缺失、部分、错误实现批准需求，或加入未请求范围 |
| `STANDARDS` | 是否违反冻结仓库规则，或出现未被工具覆盖的可维护性 smell |
| `CORRECTNESS_REGRESSION` | 状态/数据/控制流/边界是否错误，测试断言是否不足，是否产生回归 |
| `SECURITY_COMPATIBILITY` | 授权、注入、泄露、契约/Schema/消息/配置兼容、迁移回滚和发布顺序是否安全 |

四轴分别给 `PASS | PASS_WITH_GAPS | FAIL`，不做评分平均。工具已经确定性拦截的格式问题不重复报告。无 Finding 的轴为 `PASS`；只有非阻断 minor judgement call 的轴可为 `PASS_WITH_GAPS`；出现 hard defect 或 major 以上 Finding 的轴必须 `FAIL`。

## Finding

每条 Finding 必须包含：

```json
{
  "finding_id": "F-001",
  "severity": "major",
  "axis": "CORRECTNESS_REGRESSION",
  "acceptance_id": "AC-001",
  "repository_id": "orders",
  "candidate_sha": "<40-char sha>",
  "path": "src/main/java/OrderService.java",
  "line": 42,
  "observed_failure": "取消订单后仍写入完成状态",
  "evidence": "固定 diff 与 TC-004 失败证据",
  "repair_contract": "仅修正取消分支状态写入，并补充同一公开 seam 回归证明",
  "kind": "hard_defect",
  "confidence": "high"
}
```

Severity 为 `blocker | critical | major | minor`；Kind 为 `hard_defect | judgement_call`。`STANDARDS` 轴的 smell 必须使用 `judgement_call`，明确仓库规则违反才可 `hard_defect`。Finding 只报告能够定位、解释失败和形成最小修复契约的事项。

## Repair Packet

`FAIL` 时按责任范围生成最小 Repair Packet：Finding ID、owner role、固定失败候选、允许修改路径、必须保持的 Contract、修复后必跑 Case/Gate。Reviewer 不执行修复。候选变化使旧 Test、Verification 和 Review 结果失效。

## 输出

```text
zhuanspec/changes/<change-id>/artifacts/review/
├── findings.json
└── report.md
```

报告记录四轴结论、Findings、waivers、向量恒等式和只读声明。Result Envelope summary 不超过 240 字，不含完整 Finding。Hooks 为 `DEFERRED` 时如实透传，不伪造事件。
