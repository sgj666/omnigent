# 设计依据与裁剪记录

本文件只供维护和评审时读取。

## 历史逻辑

- 保留现有 ZhuanSpec `proposal.md + design.md + specs/** + tasks.md`、strict validation、外部依赖、兼容性、测试 seam 和任务依赖。
- 合并旧 `techDesign/tech-spec.md` 与 `design.md` 的重复技术方案职责，`design.md` 成为唯一技术方案。
- 把旧 proposal Command 中事实调查交给 Research Engineer，把业务澄清交给 Requirement Analyst/Coordinator。
- 舍弃强制逐字段提问、模板填满、分阶段长进度块和按技术层顶层拆任务。

## 开源依据

- OpenSpec：保留 proposal/specs/design/tasks Artifact Graph、delta spec 和严格验证，吸收 fluid action 而非复制 provider commands。
- Grill：只消费已解决 Decision Frontier，不在综合阶段重新 grilling。
- Matt Pocock `to-spec`/`to-tickets`：验收行为落 spec；任务采用 tracer-bullet 纵向切片和显式 blocker。
- Superpowers `writing-plans`：每个任务适合 Fresh Context、具有明确验证和最小范围。

## 角色边界

Proposal Architect 写提案图并冻结共享契约；不批准、不实现、不测试、不做长期知识沉淀。实施学习需要改变行为时，必须先更新提案图，再由 Coordinator 重开门禁。
