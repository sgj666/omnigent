---
name: engineer-tests
description: 从批准的 Acceptance Criteria 和固定候选向量生成风险驱动测试矩阵，在 author 模式仅编写获授权的测试与 fixture 并返回不可变测试引用，在 verify 模式运行 unit、component、API、integration 或 WebUI 测试并锚定客观证据。用于 Test Engineer 独立设计和执行测试；不用于修改生产代码、代替 TDD 实施、代码审查或最终交付验收。
version: 1.2
---

# 独立测试工程

只与 Coordinator 通信。接收一个固定候选和批准 Artifact 快照；完整测试计划、handoff、结果与证据写入 Artifact，只返回短 Result Envelope。

## 执行流程

1. 按 [references/test-protocol.md](references/test-protocol.md) 校验 Task Packet。候选必须是完整多仓向量，批准 Artifact 必须带不可变引用和摘要；缺少环境、授权或数据时不得猜测。
2. 使用 `load-project-context` 的 `test` 覆盖模式定位项目测试约定、历史 Case、API/WebUI gateway 和代码 seam。它只用于导航，批准快照和固定候选才是本任务权威输入。
3. 为 Acceptance Criteria 生成风险驱动 `test-plan.json`。按变更风险选择最小充分层级，不执行固定“六轨”；每个阻断 AC 至少映射一个阻断 Case，断言来自 Spec 或已批准示例，不能复算实现结果。
4. `author` 模式只在 `test_write_scope` 内写测试、fixture 和测试辅助代码，提交不可变 test ref，返回 `TESTS_AUTHORED`。这不是测试通过；Coordinator 必须先让 Integrator 合入测试，再形成新候选。
5. `verify` 模式对完全集成的固定候选运行所选测试。不得修改生产代码、测试、fixture、断言或候选引用；失败时保留最小复现并返回 `TEST_FAIL` 或 `TEST_BLOCKED`。
6. API 或 WebUI 需要项目 gateway 时，只读取 Task Packet 指定路径，或 `.claude/.codex` 中第一个匹配的 `api-test-flow` / `zz_webui_test` 说明。禁止继承其直接询问用户、默认生产环境、自动安装、上传或派生 Agent 行为；这些动作必须已在 Packet 中授权。
7. 用 `python3 scripts/validate-test-artifact.py plan|handoff|result <json>` 校验正式产物。证据必须能在 Attempt 清理后重新解析，不能返回临时绝对路径。

## 边界

- TDD 的 RED-GREEN 循环属于 Frontend/Backend Implementer；本 Skill 可以提供验收测试设计，但不替实施者签署 TDD。
- WebUI 自动化由 Test Engineer 所有。实施者 smoke、Verifier 证据检查和 Reviewer 风险判断都不构成 WebUI 验收。
- 不修改生产代码，不弱化断言，不为通过而跳过 Case，不修复业务缺陷。
- 不直接联系用户或其他 Worker，不派生 Agent，不 push、部署或修改共享环境。
- 缺浏览器、环境、凭证、测试数据或授权时返回 `TEST_BLOCKED`/`TEST_SKIPPED`；阻断 AC 没有明确 waiver 时不得 `TEST_PASS`。

维护或评审本 Skill 时读取 [references/design-basis.md](references/design-basis.md)；普通测试任务不要加载设计历史。
