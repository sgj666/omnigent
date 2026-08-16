# 工作流状态机

## 状态主链

```text
intake
→ preflight
→ requirement
→ research
→ proposal
→ planning
→ implementation
→ integration
→ testing
→ verification
→ review
→ knowledge_close
→ archive
→ pending_delivery
→ delivered
```

状态表示已满足的交付条件，不表示必须召开一次会议或询问一次用户。简单工作项仍逐状态推进；不适用阶段登记带理由的 `not-applicable` Artifact，而不是以通用 waiver 绕过状态机。

## 各阶段最小产物

| 状态 | 最小产物或证据 |
|---|---|
| `preflight` | Harness/Bundle/Worker/Skill 可用性、Hooks 模式及对应能力检查结果 |
| `requirement` | 需求问题、拆分建议、风险、验收草案和必要的人类确认 |
| `research` | 知识与代码研究报告，包含来源和未决事实 |
| `proposal` | `proposal.md`、`design.md`、`specs/**`、`tasks.md` |
| `planning` | 已批准计划、冻结共享 Contract，以及安全检查或不适用理由 |
| `implementation` | Attempt、Worktree Lease、Commit/变更引用与实现报告 |
| `integration` | 不可变 handoff refs、冲突/集成检查与 COMPLETE candidate vector |
| `testing` | Test Case、命令、退出码、API/WebUI 结果与失败证据 |
| `verification` | 同一 candidate vector 对批准方案和 AC 的机械证据验收 |
| `review` | 独立 Reviewer 四轴结论与问题清单 |
| `knowledge_close` | 长期知识沉淀决策，以及过程摘要、纠正和准确性投影 |
| `archive` | 提案、证据、决策和知识闭环的归档清单 |
| `pending_delivery` | 完整交付包和待人批准标记 |
| `delivered` | 人类批准记录 |

## 恢复与幂等

按以下顺序恢复：

1. 看板 WorkItem 的用户可见状态、父子关系和分配；
2. Ominigent Run、Session、Attempt、Worktree Lease 和 Agent 状态；
3. Delivery/ZhuanSpec 控制面的 Coordinator Ledger、计划、依赖、状态转换与 `task_id + attempt`；
4. ZhuanSpec Artifact Registry 中的产物、Commit 和验证证据；
5. Inbox 消息树中的未处理 Envelope；
6. 聊天摘要只用于解释，不作为状态真相源。

若任务已是 `DONE` 或 `DONE_WITH_CONCERNS`，且 Artifact 与 Evidence 仍可读取，则不得重跑。若证据失效，创建新 Attempt 并记录失效原因，不覆盖旧记录。

失败必须分类处理：Boot Failure 修复启动条件后重试；Task Failure 将具体证据发回原职责 Worker；Runaway 必须先取消当前 Attempt，确认停止或记录取消状态后，才能用同一任务契约创建有限次数的新 Attempt。不得让失控 Worker 与替代 Worker 同时写同一范围。

## 转换规则

- 只允许文档主链中显式列出的下一状态；不提供通用跳转 waiver。
- 每次转换必须携带 `transition_id`、`run_id`、`idempotency_key`、`expected_version`、`current_version` 和目标阶段所需的 `kind/ref` Evidence。
- 相同 `transition_id` 的已应用转换可按同状态幂等重放；不同 ID 的 self-transition 非法。
- `delivered` 只能从 `pending_delivery` 进入，并必须携带 `human-approval` Evidence。
- `blocked`、`failed`、`cancelled` 是运行状态，不是 Phase；发生阻塞时保持当前 Phase 并更新 status。
- Gate 失败保持原状态并产生阻塞或修复任务，不伪造回退后的成功状态。
- 用 `scripts/validate-contract.py transition` 校验结构；业务门禁仍以已登记产物为准。

## Task 控制面

```text
Requirement/Delivery PlannedTask
  ↔ WorkItem
    ↔ WorkItemRun
      ↔ Runtime Run / Worker Session / Attempt / Worktree / Artifact
```

- Requirement Gate 批量 upsert `task_kind=requirement`，初始 `backlog`、Agent/Worker 都为空。
- Planning Gate 增量 upsert `task_kind=delivery`，使用 `parent_task_key` 和 `depends_on` 形成可执行图。
- `task_key` 在同一 Delivery Run 内稳定；计划修订只能更新，移除项标为 `cancelled`，不能删除历史 Task。
- 分配不是看板状态：`assignee_agent_id` 指向 zhuanharness，`assignee_worker_name` 指向内部 Worker；未分配保持空。
- 依赖完成且已分配时进入 `todo`/Ready Queue；派发后 `in_progress`；产物到达后 `review`；门禁通过后 `done`。
- 用户和 Coordinator 可随时增加通用 Task；Worker 只能提出建议，由 Coordinator 决定是否物化。
