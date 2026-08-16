# 设计依据与裁剪

| 来源 | 保留 | 改造或舍弃 |
|---|---|---|
| Grill `frontend-delivery` | 精确 base materialization、owned paths、不可变 handoff ref、前端规则隔离 | 保留项目 `AGENTS.md`/`CLAUDE.md` 可见；`claude-native` 改为 Bundle 的 `claude-sdk`；不关闭沙箱 |
| Superpowers `using-git-worktrees`、`executing-plans` | 隔离修改、小任务、验证后交付 | Worktree 生命周期由 Ominigent 管理，Skill 不自行创建 |
| Matt Pocock `implement`、`tdd` | 依据 Spec、公共 seam、经常运行精确检查 | 不自动调用 Reviewer、不直接面向用户、不提交到用户分支 |
| ZhuanSpec 前端 Rules 与 apply-agent | 前端规范按需加载、验收追踪 | 舍弃 Commands 驱动、全量规则和长进度输出 |

Worktree 隔离代码写入；`skills: none + remote_skills` 隔离能力上下文。两者职责不同。
