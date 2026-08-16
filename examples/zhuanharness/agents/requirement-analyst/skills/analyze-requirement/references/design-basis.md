# 设计依据与裁剪记录

本文件只供维护和评审时读取；普通需求分析不要加载。

## 历史基线

- 现有 ZhuanSpec `proposal.md` Command：保留提案前澄清、知识检索优先、范围检查、验收标准和外部依赖风险。
- 现有 ZhuanSpec `techDesign.md` Command：保留共享 Contract、兼容性和跨应用影响检查。
- 真实工作区：`/Users/zzzz/workbench-projects/projects/二奢寄卖-清分后不支持判商家责任`。
- 知识入口：沿用并通过 `load-project-context` 适配既有 `load-project-knowledge`，不在需求分析 Skill 内重建检索系统。

## 开源方法

- Grill `grilling`：吸收聚焦追问和主动暴露规格缺口；舍弃为完整度机械穷举问题。
- Superpowers `brainstorming`：吸收实施前消除关键不确定性、一次处理一个边界和 Fresh Context；不让需求分析师越权实施。
- OpenSpec：Requirement Review 作为 `proposal/specs/design/tasks` Artifact Graph 的上游输入，而不是替代提案结构。
- Polly：吸收 Coordinator 唯一入口、Worker 单一 scoped task、只向 Coordinator 回报、Artifact-first 与短消息交付。

## 保留、改造与舍弃

| 类型 | 内容 |
|---|---|
| 保留 | 业务澄清、技术可实现性审查、验收标准、范围/依赖/安全/兼容风险 |
| 改造 | 先轻量知识检索；事实缺口路由 Research；大需求按业务能力或纵向切片拆分；输出机读 Manifest |
| 舍弃 | 基于 Commands 的整套重上下文；所有模糊点直接问用户；分析阶段编写提案/技术方案；按前端/后端技术层拆业务能力 |

## 角色边界

Requirement Analyst 只负责把需求变成可研究、可决策、可提案、可验收的输入。深度事实调查属于 Research Engineer；`proposal.md`、`design.md`、`tasks.md` 属于 Proposal Architect；实现、测试、验证与审查属于后续独立 Worker。
