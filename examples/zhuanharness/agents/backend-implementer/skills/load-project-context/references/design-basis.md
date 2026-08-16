# 设计依据与裁剪记录

## 权威历史基线

用户指定的源 Skill：

```text
/Users/zzzz/Documents/spec_repo/specs/common/claude/.claude/skills/load-project-knowledge
```

2026-08-12 审计的 `SKILL.md` SHA-256：

```text
9195fc6b341807fbc55fe67be06f8ff2bb2685bc954089e14cc1eaed47c74694
```

关联 references 为 `reference/LoadLLMWiki.md` 和 `reference/LoadProjectWiki.md`。目标仓库同时已有两份 `name: load-project-knowledge` 的不同镜像；Ominigent 会把重复名称全部标成错误，因此本适配 Skill 使用唯一名称 `load-project-context`，不新增第三份同名实现。

## 保留

- `knowledge-agent → llmwiki → project-wiki` 三路优先级和失败 fallback。
- 区分 `.project-wiki/index.md`、`zhuanspec/knowledge/index.md` 和 `project.md`。
- L1/L2/L3、导航表和子文档的渐进加载。
- llmwiki 优先于裸代码搜索；cross-stack 场景前后端双端覆盖。
- 真实 `expert_id` 由调用方传入，不在 Skill 中写死。
- 检索后立即回到原始工作流，不把加载上下文当最终答案。

## 舍弃

- 不把完整路由细节全部放在 `SKILL.md`；长流程按需放 references。
- 不允许普通加载入口调用 deposit、feedback、mining 等知识写操作。
- 不固定每次都进行最多 10 轮向量检索；先用 5 轮，只有完全无有效路径才扩展。
- 不把完整检索结果塞入 Worker 消息。

## 改造

- 显式接收 `workspace_root`、可选 `worktree_root` 和 `coverage`，适配 Ominigent Attempt Worktree。
- Harness 阶段确定性映射到历史 `propose | tech-design | apply`，保留知识日志兼容性。
- 完整结果写 Artifact，Agent 间只传短 Envelope。
- `zhuanspec/knowledge` 改为三路都始终检查；原逻辑在 knowledge-agent 命中时跳过本地沉淀，会使知识闭环的新知识无法被召回。
- 增加输入输出机械校验，避免错误 stage、expert、coverage 和缺失本地知识检查。

## 理由

这些改造不改变知识系统和检索优先级，只解决多 Agent 下的工作空间定位、消息截断、阶段兼容和本地知识漏检。名称变化是仓库当前重复 Skill 的必要寻址适配，不代表重新发明能力。

## 开源方法补充

- Matt Pocock Engineering `research`（commit `84fdeffd12f2ee307994d1eb6feb48173b6e0502`）：保留高可信来源和 claim 引用纪律；不在 Skill 内再创建 background agent。
- Superpowers `systematic-debugging`（version `6.2.0`，commit `44c9b2d6e889982ac18c27d05a19fefe335194e1`）：检索结果只能形成假设，当前代码与可复现证据负责核验。
- Ominigent 当前运行时：`remote_skills` 提供 Agent 级能力选择，Attempt Worktree 提供代码写隔离；本 Skill 只读，不自行创建 Worktree。

## 设计亮点

1. **原能力、唯一入口**：避免同名冲突，同时保留历史三路路由。
2. **本地闭环不丢失**：任何远端路径都补查本地三分区知识。
3. **双根核验**：知识来自原空间，候选实现事实可从 Attempt Worktree 验证。
4. **覆盖可裁剪**：Research 可 cross-stack，前后端实施只查本 Packet 范围。
5. **Artifact-first**：检索详情可审计，Coordinator 上下文保持短小。
