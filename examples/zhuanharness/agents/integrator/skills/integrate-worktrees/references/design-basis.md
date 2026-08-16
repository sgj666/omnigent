# 设计依据与裁剪记录

本文件只供维护和评审时读取。

## 历史逻辑

- 保留旧 Apply Wave 的依赖顺序、跨包编译、导入/契约/外部依赖和功能闭环检查。
- 用 Ominigent Attempt Worktree 取代主线程共享 checkout；用 handoff refs 和 candidate vector 取代临时目录及每 Wave 长报告。
- 独立 Integrator 负责收敛，避免任一 FE/BE Implementer 自行拥有另一侧提交或跨域语义决策。
- 舍弃主线程直接修冲突、隐式 current HEAD、stash/pull/rebase 和半成功交付。

## 开源依据

- Polly `fanout`：每个写任务使用隔离 Worktree，只有并行安全任务才能同时执行。
- Superpowers `using-git-worktrees`：隔离目录、基线验证和完成前 clean 检查。
- OpenSpec Artifact Graph：集成只消费已满足依赖的任务产物，不能用任务声明替代实际证据。
- Ominigent：Attempt Worktree 是平台租约且会回收，必须在结束前用不可变 refs 保留交付。

## 角色边界

Integrator 必须独立。它只验证和应用已批准提交、运行交叉检查并发布 candidate vector；文本或语义冲突回到原 Implementer，不能在集成角色中悄悄改变业务行为。
