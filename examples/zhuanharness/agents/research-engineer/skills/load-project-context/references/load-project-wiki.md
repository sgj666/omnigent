# project-wiki 路径

本流程基于历史 `LoadProjectWiki.md`，用于 llmwiki 不可用、入口缺失或查询失败时。

1. 读 `workspace_root/zhuanspec/project.md` L1：服务分组、禁改/迁移原则和核心调用路径。
2. 始终检索 `workspace_root/zhuanspec/knowledge/index.md` 和 active 三分区，不引用 Deprecated 折叠区。
3. 只读 matched service 的 L2 卡片；跨链路或架构任务才读 L3。
4. 对每个 matched service 先读 `.project-wiki/project.md` 的导航表，不全量加载子文档。
5. 按任务选择 1–2 个子文档：接口查 API、状态查数据模型/状态机、配置查配置管理、架构查分层与依赖、测试查业务路径和 Case。
6. 文档不足时按“子文档关键路径 → matched service 内 `rg` → 全局 `rg` 兜底”检索。全局兜底要标注 wiki 未覆盖。

一次默认最多加载 4 个服务的文档。超过时按业务链拆批，避免上下文膨胀。
