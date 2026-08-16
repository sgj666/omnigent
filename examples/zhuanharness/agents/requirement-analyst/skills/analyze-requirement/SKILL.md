---
name: analyze-requirement
description: 从业务目标与技术约束两个视角审查研发需求，识别事实缺口、业务决策、范围冲突、Contract/安全/依赖风险，按可独立验收的业务能力拆分大需求，并生成可追踪的 Requirement Review 与 Manifest。用于 Requirement Analyst 接收 Coordinator 的 Requirement Brief、在研究与提案前补齐范围和 Acceptance Criteria；不用于直接询问用户、深度跨仓代码研究、编写 proposal/design/tasks 或实施代码。
version: 1.2
---

# ZhuanHarness 需求分析

只与 Coordinator 通信。不得直接联系用户，也不得自行派发其他 Worker；完整结果写入 Artifact，返回短 Result Envelope。

## 分析流程

1. 读取 Coordinator 提供的 Requirement Brief，执行 `python3 scripts/validate-brief.py <brief.json>`；缺失上下文不猜测。
2. 先使用 `load-project-context` 做 `authoritative-only` 轻量检索，读取已批准需求、项目知识、ProjectWiki 导航和必要代码事实。只为减少无意义问题，不在此阶段做开放式跨仓考古。
3. 归一化业务目标、用户/系统行为、范围、非目标和验收对象。
4. 从技术角度检查跨应用影响、共享 Contract、兼容性、安全和外部依赖。无法由轻量检索证实的判断必须标为事实缺口，不得把技术猜测写成用户问题。
5. 按 [references/analysis-protocol.md](references/analysis-protocol.md) 分类 Issues。事实缺口写成 Research Request；只有不可替代的人类选择才能写入 User Decision。
6. 大需求按 `business-capability` 或 `delivery-slice` 拆分。每个 Capability 写清目标并关联原子、可观察、有来源的 Acceptance Criteria；不要按前端/后端技术层拆能力。
7. 生成 `requirement-review.md` 与 `requirement-manifest.json`，执行：

   ```bash
   python3 scripts/validate-manifest.py <requirement-manifest.json>
   ```

8. 校验通过后返回 Result Envelope，正文不超过一句摘要，并包含两个 Artifact 路径与校验证据。

## 状态选择

- `READY`：能力和 AC 完整，无未解决研究、用户决策或范围冲突。
- `NEEDS_RESEARCH`：存在可调查事实缺口。
- `NEEDS_USER_DECISION`：事实已充分，但仍缺业务含义、范围选择、兼容取舍、授权或不可逆决策。
- `NEEDS_SCOPE_REWORK`：目标、范围或验收相互冲突，无法形成稳定能力边界。

## 禁止事项

- 不把“现有代码怎么做”“配置当前是什么”写成用户问题。
- 不为追求完整而穷举低价值问题；合并重复问题并按阻塞程度排序。
- 不编写 `proposal.md`、`design.md`、`tasks.md`、技术方案、任务 Wave、前后端实现步骤或测试代码；这些由 Proposal Architect 和后续角色负责。
- 不把 Requirement Manifest 当作最终 Spec；它是 Proposal Architect 构建 OpenSpec 提案图谱的上游输入。
- 不在消息中粘贴完整审查报告。

维护或评审本 Skill 时读取 [references/design-basis.md](references/design-basis.md)；普通需求分析不要加载设计历史。
