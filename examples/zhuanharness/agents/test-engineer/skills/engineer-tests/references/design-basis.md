# 设计依据与裁剪记录

本文件只供维护和评审时读取；普通测试任务不要加载。

## 历史基线

- 旧 ZhuanSpec `test-case-generator`：保留独立验证点、覆盖矩阵、P0/P1 可追踪性；舍弃默认提交 ZZCase、默认写用户目录和在 Skill 内直接询问用户。
- 旧 `tdd-testcase-generator`：保留 QA Case、技术断言、测试层和来源追踪；不把测试设计等同于实施 TDD。
- 旧 `api-test-flow` / `zz_webui_test`：作为已有执行 gateway 按需读取；不继承其默认正式环境、全局安装、外部上传、直接用户交互或子 Agent 派生。
- 旧 `review.md`：保留测试结果与历史报告兼容语义；舍弃固定六轨、测试失败不阻断和同一角色修生产代码的模式。

## 开源方法

- Grill `test-engineering`：吸收 `author | verify` 双模式、完整候选向量、按风险选层、不可变 handoff ref 和持久 Evidence Anchor。
- Superpowers `test-driven-development`：吸收必须看见正确失败、行为断言、少 Mock；TDD 执行仍属于 Implementer。
- Matt Pocock `tdd`：吸收 public seam、纵向 slice、避免实现耦合和独立预期值。
- Superpowers `verification-before-completion`：吸收“证据先于声明”，但最终机械验收由 Verifier 独立执行。

## 角色边界

Test Engineer 负责测试设计、获授权的测试资产和独立执行证据；不实现业务、不审查代码质量、不签署最终交付。`author` 产生的新测试必须先由 Integrator 合入新候选，再以 `verify` 模式运行。
