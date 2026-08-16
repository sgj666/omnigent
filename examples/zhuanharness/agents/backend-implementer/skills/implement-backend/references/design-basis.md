# 设计依据与裁剪

| 来源 | 保留 | 改造或舍弃 |
|---|---|---|
| Grill `backend-delivery` | 精确 base、owned paths、不可变 ref、后端规则隔离、跨服务契约意识 | 保留项目 `AGENTS.md`/`CLAUDE.md` 可见；适配 `claude-sdk` 与真实沙箱 |
| Superpowers `using-git-worktrees`、`executing-plans` | 隔离修改、按计划小步交付 | Worktree 生命周期由 Ominigent 管理，Skill 不自行创建 |
| Matt Pocock `implement`、`tdd` | 依据 Spec、公共 seam、纵向测试 | 不自动调用 Reviewer、不直接面向用户、不提交用户分支 |
| ZhuanSpec 后端 Rules 与 apply-agent | API/DAO/安全规则按需加载、验收追踪 | 舍弃 Commands 驱动、全量规则和长进度输出 |

Worktree 隔离代码写入；`skills: none + remote_skills` 隔离能力上下文。两者职责不同。
