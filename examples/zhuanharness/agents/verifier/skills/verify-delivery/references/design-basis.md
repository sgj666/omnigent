# 设计依据与裁剪记录

本文件只供维护和评审时读取；普通验收任务不要加载。

## 历史基线

- 旧 `tc-implementation-verify`：保留 TC 与需求追踪目标；舍弃按类名、方法名或组件名存在即判实现。
- 旧 `spec-code-consistency-check`：保留 Spec is Truth 与未覆盖项报告；舍弃“任一关键词命中即 covered”、方法行数和调用链启发式。
- 旧 `review.md`：保留归档前门禁、结果 Artifact 与历史报告兼容语义；舍弃 Verifier 自己补测试、修代码和手工编造 JSON。

## 开源方法

- Superpowers `verification-before-completion`：直接吸收 Evidence before claims、现场运行完整命令、读取退出码和“Agent completed 不等于完成”。
- Grill `test-engineering` / `independent-review`：吸收固定完整多仓向量、持久 Evidence Anchor 和 `tested == final`；将机械验收从测试与代码审查中独立出来。
- OpenSpec：以批准 proposal/design/decisions/specs 的不可变快照作为验收权威来源，而不是 mutable caller working tree。

## 角色边界

Verifier 回答“同一最终候选是否有足够客观证据证明批准内容已经实现”。Test Engineer 负责设计和运行测试；Reviewer 负责规格、标准、正确性、安全兼容风险；Implementer 负责修复。Verifier 不承担三者职责。
