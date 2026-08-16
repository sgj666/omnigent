# Delivery Verification Protocol

## Verification Packet

至少包含 `task_id`、`requirement_id`、`change_id`、批准 `artifact_snapshot`、`base_vector`、`final_candidate_vector`、Test Engineer 的 `tested_vector` 与 Evidence Anchor、Acceptance Criticality、必需 Gate/Command、批准 waivers 和真实 `hook_context`。

`artifact_snapshot` 必须含 immutable ref、完整 commit SHA、blob path 和 SHA-256。所有向量必须 `complete: true`，逐仓使用稳定 `repository_id` 与完整 40 位 SHA；任何 candidate 变化都使旧 Test/Verification/Review 结果失效。

## Gate Function

对每个声明执行：

1. `IDENTIFY`：标出能够证明该声明的完整命令；
2. `RUN`：在固定候选上现场运行，不接受“之前跑过”；
3. `READ`：读取完整输出、退出码、失败数量和警告；
4. `ANCHOR`：把原始输出锚定为可重新解析的 immutable evidence；
5. `VERIFY`：证据支持才标 PASS，否则 FAILED 或 BLOCKED。

每个 Gate 至少包含 `gate_id`、`kind`、`required` 和 `status`。`PASS`/`FAIL` 必须包含 `execution`，其中含 `command`、`proof_type`、`exit_code`、起止时间、candidate vector digest 和 Evidence Anchor；`BLOCKED`/`SKIPPED` 必须包含具体 `reason`，不得伪造一次执行。`proof_type` 必须匹配声明：`lint | build | test | acceptance | artifact-integrity`；不能用 lint 证明 build，也不能用 build 证明业务 AC。

## Acceptance 追踪

每个阻断 AC 必须映射到至少一个实际 Case 和通过的 Evidence Anchor：

```json
{
  "acceptance_id": "AC-001",
  "blocking": true,
  "status": "PASS",
  "case_ids": ["TC-001"],
  "evidence": [{"repository_id": "control", "ref": "refs/...", "commit_sha": "...", "blob_path": "...", "sha256": "...", "resolvable": true}]
}
```

`SKIPPED` 的阻断 AC 必须有明确批准 waiver；`BLOCKED` 或无证据的阻断 AC 禁止 `VERIFIED`。关键词、源文件路径、覆盖率百分比和 Worker summary 只能帮助定位，不能替代行为证据。

## 输出

```text
zhuanspec/changes/<change-id>/artifacts/verification/
└── verification-report.json
```

报告至少记录 Artifact 完整性、向量恒等式、Gate 结果、AC 追踪、waivers、Verifier 只读声明和最终状态。Result Envelope summary 不超过 240 字；完整日志只通过 Artifact 引用传递。Hooks 为 `DEFERRED` 时如实透传，不伪造事件。
