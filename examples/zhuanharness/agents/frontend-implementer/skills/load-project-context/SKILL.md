---
name: load-project-context
description: 渐进式加载 ZhuanSpec 项目知识与代码导航上下文。基于既有 load-project-knowledge 改造，依次路由 knowledge-agent、llmwiki、project-wiki，并始终补查 zhuanspec/knowledge；用于 Coordinator 回答已有资料可回答的问题，或其他 Worker 在设计、实施、测试、验证和审查前缩小服务与代码范围。完整结果必须写入 Artifact，不用于知识沉淀或替代深度研究。
version: 1.2
---

# 加载项目上下文

本 Skill 是已有 `load-project-knowledge` 的 Ominigent 适配入口，不是新的知识系统。它只读检索并返回可引用上下文；知识写回走独立闭环。

## 输入

先构造请求并运行：

```bash
python3 scripts/validate-context.py request <request.json>
```

请求至少包含：

- `task_id`、`workspace_root`、`query`、`harness_stage`；
- `coverage`：`cross-stack | frontend | backend | test | authoritative-only`；
- `artifact`：完整结果的目标路径；
- 可选 `expert_id`：`1=product`、`2=technical`、`3=test`...；
- 实施候选代码与原空间不同时，传 `worktree_root`，但不得写入。

脚本将 Harness 阶段映射到已有知识日志阶段：`propose | tech-design | apply`。禁止自行发明底层 stage。

## 三路检索

无论走哪一路，都先读取 `workspace_root/AGENTS.md`、`CLAUDE.md`（存在时）和 `zhuanspec/project.md` 的 L1，再缩小 `matched_services`。

1. **knowledge-agent**：请求带真实 `expert_id` 且公共 `knowledge-agent-action` 可用时，调用其 `search` 或 `search-no-code`。只允许检索接口，不允许本 Skill 调用 deposit、feedback、mining 或其他写接口。失败或空结果进入下一路。
2. **llmwiki**：相关服务存在 `.project-wiki/index.md` 且 `llmwiki --version` 成功时，按 [references/load-llmwiki.md](references/load-llmwiki.md) 执行向量检索。失败进入下一路。
3. **project-wiki**：按 [references/load-project-wiki.md](references/load-project-wiki.md) 渐进读取宏观/微观文档，再在限定服务范围做代码检索。

`zhuanspec/knowledge/{troubleshooting,best-practices,implicit-conventions}` 必须始终独立检查，包括 knowledge-agent 命中时；跳过 Deprecated 条目。远端或向量库不会自动包含这部分新沉淀知识。

## 覆盖范围

- `cross-stack`：L1 同时识别前后端时，两端至少各执行一次有效检索；
- `frontend` / `backend`：只在 Task Packet 指定的对应服务范围检索；
- `test`：围绕验收、接口、UI 路径和历史 Case，端到端任务按 cross-stack；
- `authoritative-only`：只读批准产物、稳定知识和已有 Knowledge Artifact，不进行开放式代码考古。

## 输出

完整结果写入请求的 `artifact`，至少包含路径选择、原因、本地知识检查、命中服务、覆盖情况和 Artifact 元数据。然后执行：

```bash
python3 scripts/validate-context.py result <artifact.json>
```

调用方继续原工作流，不把完整 JSON 发给 Coordinator。跨 Agent 只返回 Artifact 路径、一句摘要和未决 `FACT_GAP`。

维护本 Skill 时读取 [references/design-basis.md](references/design-basis.md)；普通运行不要加载设计历史。
