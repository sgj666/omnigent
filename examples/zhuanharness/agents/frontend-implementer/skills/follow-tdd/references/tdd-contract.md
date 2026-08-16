# TDD 契约

## 输入

```yaml
tdd_policy:
  mode: required | conditional | exempt
  source: project | proposal | user-decision
  reason: <已批准理由>
  exceptions_allowed: true | false
public_seams: [<可观察入口>]
acceptance_ids: [AC-001]
```

`conditional` 必须在 Task Packet 中带 `resolved_mode: required | exempt` 及依据，Implementer 不能临场裁决。

## 证据

每个 slice 同时记录 RED 与 GREEN：

```json
{
  "task_id": "FE-001",
  "candidate_sha": "<40-64 lowercase hex>",
  "policy": {"mode": "required", "source": "proposal", "reason": "observable behavior"},
  "cycles": [{
    "acceptance_id": "AC-001",
    "public_seam": "OrderFilter",
    "red": {"command": "...", "exit_code": 1, "observed_at": "2026-08-12T10:00:00+08:00", "failure_reason": "expected completed rows only", "log_anchor": "git:refs/...@<sha>:artifacts/logs/red.log#sha256=<digest>"},
    "green": {"command": "...", "exit_code": 0, "observed_at": "2026-08-12T10:10:00+08:00", "log_anchor": "git:refs/...@<sha>:artifacts/logs/green.log#sha256=<digest>"}
  }]
}
```

日志必须可在 Attempt 清理后解析。临时绝对路径和聊天文字不是持久锚点。

## 例外

例外请求至少说明：目标行为、尝试过的 seam、失败证据、替代验证、风险与最小可行改造。只有 Coordinator 能把人类或批准 Proposal 的决定固化进新 Task Packet。
