# 设计依据与裁剪记录

本文件只供维护和评审时读取；普通审查不要加载。

## 历史基线

- 旧 ZhuanSpec `review.md` 与 `code-review-expert`：保留 Spec、编码规范、安全、兼容、编译和结构化报告目标；舍弃 Reviewer 自动修代码、固定循环和缺真实证据仍可手编 JSON。
- 真实项目 Rules：把 `AGENTS.md`、`CLAUDE.md`、`.claude/rules` / `.codex` 作为冻结 Standards 来源，但 Finding 必须引用 Packet 快照或固定 commit，不读 mutable caller root 下的同名文件作结论。

## 开源方法

- Grill `independent-review`：作为直接基线，吸收固定 base/tested candidate、四轴审查、Evidence Anchor、向量恒等式和最小 Repair Packet。
- Matt Pocock `code-review`：吸收 Standards 与 Spec 分轴、固定 comparison point、仓库规则优先、Fowler smell 仅为 judgement call；舍弃内部继续派生两个 sub-agent，因为 ZhuanHarness Worker 禁止派生。
- Superpowers `requesting-code-review`：吸收 Fresh Context、精确 base/head 与规格输入；不把整个实现会话历史交给 Reviewer。
- Superpowers `receiving-code-review`：技术反馈必须由 Coordinator/Implementer 先验证再修复，Reviewer 不自行实施建议。

## 角色边界

Reviewer 回答“已测试和验收的实现是否仍有交付风险”。Test Engineer 提供测试证据，Verifier 检查证据与声明，Implementer 修复；Reviewer 不兼任任何一方。
