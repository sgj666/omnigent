# Decision Frontier 与门禁策略

## 谁回答 Worker 的问题

按顺序判断：

1. 需求、提案、知识、代码或运行证据已经给出答案：Coordinator 直接回答并引用来源。
2. 答案是可调查事实：委派 Research Engineer；代码也是知识，不另设重复的 Code Analyst。
3. 缺少业务含义、范围选择、兼容取舍、新授权或不可逆决策：Coordinator 合并重复项后询问用户。

不得用“更稳妥”为由把事实调查推给用户，也不得在事实缺失时猜测。

## 路径裁剪

### 简单工作项

局部、可逆、不改变外部契约、不涉及安全敏感面且验收明确。可以跳过独立研究、完整提案或集成阶段，但必须保留需求标识、写入边界、实际验证和交付证据。

### 标准工作项

使用完整需求确认、研究、提案、实施、集成、测试、验证、审查和知识闭环；只有存在人类决策时才停下来询问。

### 高风险工作项

涉及权限、隐私、资金、数据迁移、不可逆操作、跨系统契约或大范围兼容时，必须在 `planning` 登记安全门禁证据，并执行独立测试和独立审查，最终停在 `pending_delivery`。

路径分类及 waiver 写入 Ledger，后续发现风险上升时立即升级路径，不需要等用户重新启动流程。

## 并行门禁

- `hooks_mode=DEFERRED`：如实记录 Hook 缺口，不因此阻止派发；不得声称已安装或已有过程数据。
- `hooks_mode=ENFORCED`：`zhuanspec init --harness` 未安装、项目 Settings 被关闭、Attempt bootstrap 未完成或必需 Hook 缺失时阻止派发。
- 前后端共享 Contract 未冻结：阻止并行，先交 Proposal Architect 或对应契约负责人完善。
- 文件写入范围重叠：由 Coordinator 改为串行或拆分不同 Worktree Lease。
- 只读研究与互不依赖任务：允许并行。
- Worker 不得自行创建下级 Worker；所有新委派经过 Coordinator。

## 失败路由

| 类型 | 处理 |
|---|---|
| Boot Failure | 记录环境/Skill/权限问题，修复启动条件后重启同一任务 |
| Task Failure | 将证据和问题发回原 Implementer，创建新 Attempt |
| Runaway | 先取消当前 Attempt，保留日志，再有限次重派 |
| Requirement Blocker | 先由 Coordinator/Research Engineer 查证；确属人类决策才询问用户 |

默认 Fix Loop 最多两轮；超过后升级给 Coordinator 重新拆解或报告阻塞，不无限重试。

## 完成门禁

Worker 声明不是证据。Coordinator 必须检查 Artifact、命令、退出码、测试摘要、变更引用和适用的独立结论。Test Engineer 负责 Case/API/WebUI 验证，Verifier 对同一候选执行批准方案与 AC 的机械验收，Reviewer 负责最终独立代码审查；三个角色的产物分别登记。

## 过程采集门禁

- 过程采集属于项目级生命周期 Hook，不属于任何 Worker Skill。
- `DEFERRED` 模式不采集事件；未来切换为 `ENFORCED` 后，每个 Worker Attempt 启动前必须物化共享指令和 ZhuanSpec 控制资产。
- Worker Hook 只追加唯一 Attempt 事件分片；Coordinator/Projector 负责归并为 `progress.json`、准确性和交付摘要。
- 不允许多个 Worker 对同一个聚合 JSON 做读改写；`ENFORCED` 模式下 Hook 或事件分片不可用时停止派发，不静默降级。
