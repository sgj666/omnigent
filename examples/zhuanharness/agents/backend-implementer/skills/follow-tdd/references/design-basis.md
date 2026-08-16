# 设计依据与裁剪

| 来源 | 保留 | 改造或舍弃 |
|---|---|---|
| Superpowers `test-driven-development` | 必须观察正确 RED、最小 GREEN、测试行为 | 不机械要求所有文件类型 TDD；例外由显式策略控制 |
| Matt Pocock `tdd` | 公共 seam、独立真值、纵向 slice、避免实现耦合 | seam 已在 Proposal/Packet 冻结，Worker 不直接询问用户 |
| ZhuanSpec `tdd-apply-agent` | 前后端均可 TDD、RED/GREEN 与验收追踪 | 舍弃“只有提供外部 case 才 TDD”和一套模板机械覆盖所有技术栈 |
| Grill frontend/backend delivery | Worktree 内执行、WebUI 后置验收 | 抽出为共享 Skill，避免前后端重复且不把 WebUI 签署权交实施者 |

TDD 是 Implementer 的实施方法，不是独立 Worker。Test Engineer 独立负责风险驱动 case 与 API/WebUI 验收。
