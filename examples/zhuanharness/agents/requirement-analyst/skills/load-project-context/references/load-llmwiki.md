# llmwiki 路径

本流程基于历史 `LoadLLMWiki.md`，保留向量优先、前后端覆盖和有限 fallback。

1. 从 `workspace_root/zhuanspec/project.md` 读取 L1，识别候选服务；只按需读 matched 服务的 L2，跨链路或架构任务才读 L3。
2. 检索 `workspace_root/zhuanspec/knowledge/index.md` 和 active 三分区。索引缺失时记录，不阻断其他路径。
3. 从每个目标服务的 `.project-wiki/index.md` 提取真实项目名和 query 指令；禁止伪造 projectName，也不要向 query 追加目录参数。
4. 依次用业务词、代码实体词、同义词和组合词查询。默认最多 5 轮；没有任何有效路径时才扩展到 10 轮，避免历史流程固定跑满。
5. `coverage=cross-stack` 且同时涉及前后端时，两端至少各有一次有效 query 后才读取命中文件。
6. 只读命中关键文件；需要确认方法体、字段或引用时，在 matched service 中用 `rg` 验证。
7. 10 轮仍未命中时转 project-wiki 路径；最终 grep 仍限定 matched service。全局检索是最后兜底，必须标记 `fallback_triggered=true` 和未验证风险。

工作空间与候选代码分离时，知识导航从 `workspace_root` 读取，当前实现事实从 `worktree_root` 读取；输出要标明核验根和 candidate ref。
