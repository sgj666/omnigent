---
name: curate-knowledge
description: 在测试和独立审查之后，将有证据的用户纠偏、根因、可复用模式、隐式契约和被替代规则去重并沉淀到 ZhuanSpec 三类长期知识及 index。用于 Knowledge Curator 执行交付闭环；不用于知识检索、过程 Hook 采集、未经验证的建议或默认写入团队政策。
version: 1.2
---

# 整理项目知识

只在 Close Gate 条件触发，不把每次任务都变成知识写入仪式。

## 流程

1. 从用户纠偏、已验证根因、通过测试/审查的复用模式、跨路径证明的隐式契约、被接受变更推翻的旧知识生成候选；运行 `python3 scripts/validate-knowledge.py candidates <candidates.json>`。
2. 按 [references/curation-protocol.md](references/curation-protocol.md) 在 active 三类和 index 中用同义词、关键词、路径去重。相同规则更新已有条目；不同规则才新建。
3. 高置信且已有测试/审查证据的工程事实可自动沉淀。新团队/业务政策、权威知识弃用、敏感信息或语义歧义必须返回 `NEEDS_USER_DECISION`，由 Coordinator 询问用户。
4. 仅写 `zhuanspec/knowledge/{troubleshooting,best-practices,implicit-conventions}`、既有 Deprecated 区域和 `index.md`；禁止静默删除冲突知识。
5. 生成 `knowledge-curation.json`，运行 `validate-knowledge.py result`，再返回短 Result Envelope。

## 边界

- 不做知识检索或代码研究，不修改提案、产品代码、测试、Git refs 和 Hook 事件。
- 不直接联系用户或其他 Worker，不自行派生 Worker。
- 不沉淀任务状态、文件清单、普通语言常识、临时环境信息、未验证 Reviewer 建议或敏感凭证。
- Hooks 负责采集，Projector 负责过程与准确率；本 Skill 只处理长期语义知识。

维护本 Skill 时读取 [references/design-basis.md](references/design-basis.md)；普通运行不要加载设计历史。
