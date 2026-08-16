# 设计依据与裁剪记录

本文件只供维护和评审时读取。

## 历史逻辑

- 保留 `zhuanspec/knowledge` 的 troubleshooting、best-practices、implicit-conventions 三类、统一 index、纠偏沉淀和重复检查。
- 保留旧知识引用/纠偏闭环的来源可追踪性，但不复用按阶段扫描全部 Read/Write 的重型知识分析器。
- 改造为验证后条件触发：高置信工程事实自动沉淀，政策/弃用/敏感/歧义才交用户决策。
- 舍弃每轮强制多选、默认全沉淀、每阶段 HTML 报告和把 Hooks 当 Skill 调用。

## 开源依据

- OpenSpec archive/sync：长期事实应在完成验证后与交付产物对齐，保留历史而非静默覆盖。
- Matt Pocock `domain-modeling`：术语和已结晶决策应即时写入稳定载体，但人类拥有业务语义。
- Polly Artifact-first：完整候选和证据落 Artifact，跨 Agent 只传短结果。
- Skill Creator：主流程精简，格式、门禁和维护依据按需加载。

## 角色边界

Knowledge Curator 是独立 Close Gate Worker，因为它需要跨研究、实施、测试和审查证据判断长期复用价值；它不承担检索，也不能取代项目级 Hooks、Projector 或 Session Analytics。
