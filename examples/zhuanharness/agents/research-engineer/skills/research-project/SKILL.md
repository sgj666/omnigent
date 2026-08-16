---
name: research-project
description: 对 ZhuanSpec 研发任务执行只读的项目知识与代码联合研究，验证当前入口、调用链、契约、影响范围和未知事实并形成可引用 Artifact。用于消费 Requirement Analyst 的 Research Request，或为提案、实施、测试、验证、审查补充源代码证据；不用于询问用户、编写提案、修改代码或沉淀知识。
version: 1.2
---

# 项目研究

代码也是知识，本 Skill 将知识研究和 Code Analyst 合为一个职责，但保留“资料导航”和“当前源码验证”两个证据层。

## 流程

1. 按 [references/research-protocol.md](references/research-protocol.md) 构造 Research Packet，先运行 `python3 scripts/validate-research.py request <packet.json>`。
2. 先调用 `load-project-context` 缩小服务和路径；再从最小外部入口沿调用、数据和副作用路径调查。ProjectWiki 只是导航，当前源码、配置和测试才证明当前事实。
3. 每个结论区分 `source_fact`、`test_assertion`、`knowledge_claim` 和 `inference`；实现相关结论必须有固定候选根下的 `path:line`，或明确标为未验证。
4. 只回答 Task Packet 中的问题。发现新的业务选择时记录为 `decision_gap` 交 Coordinator，不替用户做决定；发现可继续调查的事实时继续调查到证据饱和。
5. 完整结果写入 `zhuanspec/changes/<change-id>/artifacts/research/<research-id>.json` 及同名 `.md`，运行 `validate-research.py result` 后只返回短 Result Envelope。

## 边界

- 全程只读项目知识、代码、配置、历史变更和运行证据；不修改提案、源码、测试、知识库或 Git refs。
- 不直接联系用户或其他 Worker，不自行派生 Worker。
- 不返回原始搜索转储；只返回能改变范围、验收、契约、风险或实施定位的证据。
- 不把 archived proposal 当作当前行为，不把模型推断写成已证实事实。

维护本 Skill 时读取 [references/design-basis.md](references/design-basis.md)；普通运行不要加载设计历史。
