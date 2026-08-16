# Knowledge Curation Protocol

## 候选与证据

每个候选至少包含：`id`、`category`、`title`、`claim`、`source_change`、`evidence_refs`、`confidence`、`policy_impact`、`sensitive`、`action`。category 只允许 `troubleshooting|best-practices|implicit-conventions|deprecated`；action 只允许 `create|update|deprecate|reject`。

允许来源：显式用户纠偏、可复现且已修复的根因、通过测试与独立审查的复用模式、源码多路径证明的隐式契约、已批准变更直接取代的知识。至少一个 durable evidence ref；`create|update|deprecate` 需要 `confidence >= 0.8`。

## 写入格式

新建或触及的条目使用：

```yaml
---
id: <category-prefix-kebab-id>
category: troubleshooting | best-practices | implicit-conventions | deprecated
title: <topic>
trigger:
  keywords: []
  paths: []
severity: high | medium | low
confidence: 0.9
source_change: <change-id>
status: active | deprecated
supersedes: []
---
```

正文从 `## 适用场景` 开始，说明可复用规则与独立证据；troubleshooting 还必须有根因、排查路径和解决方案。更新条目和 index 应作为一个原子职责完成。

## 人类决策

满足任一条件时不得自动写：建立新的团队/业务政策；弃用权威指导；可能暴露敏感信息；现有证据无法从两个冲突含义中选择。Result 标为 `NEEDS_USER_DECISION` 并返回候选 ID 与理由，不在 Worker 内询问。

## Result

`knowledge-curation.json` 包含 `change_id`、`status`、`created`、`updated`、`deprecated`、`rejected`、`decision_required`、`index_path` 和 `evidence_refs`。状态为 `CURATED|NO_CANDIDATES|NEEDS_USER_DECISION|INVALID`。同一候选只能出现在一个结果集合；deprecated 必须保留旧条目并链接替代项。
