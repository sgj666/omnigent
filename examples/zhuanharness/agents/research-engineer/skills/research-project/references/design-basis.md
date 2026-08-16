# 设计依据与裁剪记录

本文件只供维护和评审时读取。

## 历史逻辑

- 保留既有 `load-project-knowledge` 的 knowledge-agent、llmwiki、ProjectWiki 渐进导航，以及 `zhuanspec/knowledge` 必查逻辑。
- 保留旧 proposal/techDesign/apply 中从入口追踪服务、配置、数据模型、依赖和测试的代码分析价值。
- 改造为一个 Research Engineer：代码也是可调查知识，不再设置重复 Code Analyst。
- 舍弃全工作区盲搜、固定十轮检索、原始日志长输出，以及把事实问题重新问给用户。

## 开源依据

- Matt Pocock `research`：优先一手来源、结论落 Markdown 并逐项引用。
- Polly `investigate`：只读 scoped task、证据化返回、与实施职责分离。
- Superpowers `systematic-debugging`：先复现和追根因，不以症状猜修复。
- OpenSpec `explore`：探索事实可随时发生，但不能把探索声明当实现完成。

## 角色边界

Research Engineer 回答可调查事实并产出 Evidence Pack；Requirement Analyst 识别问题，Proposal Architect 做方案选择和提案，Implementer 写代码，Knowledge Curator 只在验证后做长期沉淀。
