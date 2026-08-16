---
name: design-proposal
description: 将已确认的 Requirement Manifest、研究证据与项目约束综合为兼容现有 ZhuanSpec 的 proposal.md、design.md、delta specs 和 tasks.md，并校验决策、验收、任务依赖及前后端共享契约。用于 Proposal Architect 创建或修订提案；不用于重新访谈用户、调查未决事实、实施代码或批准提案。
version: 1.2
---

# 设计提案

只综合已经解决的事实和决策，不启动第二轮重型澄清。

## 流程

1. 按 [references/proposal-protocol.md](references/proposal-protocol.md) 构造输入 Manifest，并运行 `python3 scripts/validate-proposal.py input <manifest.json>`。存在未解决 Research Request、User Decision 或范围冲突时返回阻塞，不猜测填模板。
2. 读取 Requirement Review、Research Artifact、已批准决策、现行 specs、项目规则和可验证代码 anchors。只引用稳定 Artifact，不复制研究长报告。
3. 生成或修订一个现有 `zhuanspec/changes/<change-id>/`：`proposal.md`、`design.md`、`specs/**/spec.md`、`tasks.md`。`design.md` 是唯一技术方案，不再生成 `techDesign/tech-spec.md` 镜像。
4. 顶层任务按可独立验收的纵向结果组织；前端/后端只是同一 Delivery Task 下的 Worker Packet。冻结 API/message/data/state 共享契约后才允许并行。
5. 运行 ZhuanSpec strict 校验，再生成 `proposal-manifest.json` 并用 `validate-proposal.py output` 校验。只向 Coordinator 返回状态、Artifact 路径、校验命令与退出码。

## 边界

- 只写当前 change 的提案图及其 manifest；不写产品代码、测试代码、长期知识或 Hook 数据。
- 不直接联系用户或其他 Worker，不自行批准 `.approved`，不派生 Worker。
- 不把前端/后端拆成用户价值任务，不产生每任务/每 Wave 长报告。
- 新事实缺口退回 Research；新业务选择形成 Decision Gap 交 Coordinator。

维护本 Skill 时读取 [references/design-basis.md](references/design-basis.md)；普通运行不要加载设计历史。
