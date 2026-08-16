---
name: follow-tdd
description: 按已批准的 required、conditional 或 exempt 策略执行可证明的测试驱动开发，验证正确 RED 后再做最小 GREEN，并生成绑定候选提交的 TDD 证据。用于前端或后端 Implementer 实现行为变更、Bug 修复、特征测试或申请 TDD 例外；不用于由实施者自行决定是否跳过测试，也不替代 Test Engineer 的验收测试。
version: 1.2
---

# 执行 TDD

只执行 Task Packet 中已冻结的 `tdd_policy`。项目策略是基线；用户决定或批准 Proposal 可在允许范围内强化或记录例外。策略缺失、相互冲突或不可执行时返回 `TDD_BLOCKED` 或 `TDD_EXCEPTION_REQUEST`，不得自行降级。

## 循环

1. 读取 Acceptance ID、公共 seam、独立预期值、允许修改路径和必跑命令。测试 seam 不明确时停止。
2. 每次只取一个可观察行为，先写最小测试。预期值来自批准 Spec、权威示例或独立真值，不能复刻生产算法。
3. 执行精确测试并观察 RED。只有因目标行为尚未实现而产生的断言失败才是正确 RED；编译错误、环境错误、错误 fixture、测试未运行或立即通过都不算。
4. 写最少生产代码得到 GREEN，重跑同一命令，再跑受影响的现有测试。修实现，不通过放宽断言、删除 case 或加入 skip 变绿。
5. 逐个纵向 slice 重复。只在 GREEN 后做任务范围内的小型整理，并再次验证。
6. 将每个 RED/GREEN 的命令、时间、退出码、日志持久锚点、Acceptance ID 和候选 SHA 写入 `tdd-evidence.json`，运行 `scripts/validate-tdd.py`。

## 策略含义

- `required`：新行为、可复现 Bug 或有稳定公共 seam 的行为变更必须走完整 RED/GREEN。
- `conditional`：执行 Task Packet 固化的最终决定。Proposal Architect 未给出决定时不得由 Implementer暗自选择。
- `exempt`：只接受 Packet 已记录的批准理由，如 DDL、纯配置、生成代码、纯 DTO/Enum、纯静态 UI 或一次性原型；仍须运行相应验证。
- Legacy 无 seam：先写 characterization test；确实不可行时提交带证据的例外请求。

TDD 证据证明实施过程，Test Engineer 的 case matrix、WebUI/API 验收和最终 `TEST_PASS` 证明交付行为；两者不可互相替代。

## 按需读取

- 执行或维护策略时读取 [references/tdd-contract.md](references/tdd-contract.md)。
- 审查设计来源时读取 [references/design-basis.md](references/design-basis.md)，普通实施不要加载。
