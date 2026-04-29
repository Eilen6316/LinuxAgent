# 刷新 architecture.md 为当前架构真源

- **日期**：2026-04-29
- **类型**：设计变更
- **影响范围**：`.work/design/architecture.md`
- **决策者**：Agent

## 背景

`.work/design/architecture.md` 仍描述 `4.0.0.dev0` 和 Alpha 状态，且混入大量从网页复制来的 HTML 片段。当前 `pyproject.toml` 已进入 `4.0.0` / `Production/Stable`，代码也已经完成 policy engine、CommandPlan、prompt 模板化、runbook guidance、integration CI 等架构变化。

## 新决策

将 `.work/design/architecture.md` 改为当前架构的单一真源，重点记录：

- 当前版本状态以 `pyproject.toml` 为准：`4.0.0` / `Development Status :: 5 - Production/Stable`。
- Prompt 模板只位于 `prompts/`，Python 代码只通过 `prompts_loader.py` 加载。
- Runbook 作为 planner guidance，不做自然语言硬匹配或 graph 前置抢占。
- Artifact/mutation 请求统一进入 `CommandPlan`，依赖运行时或工具链时先规划环境/版本探测。
- Integration tests 作为 CI 门禁的一部分。

## 影响

- **受影响文档**：
  - `.work/design/architecture.md`
- **受影响代码**：无；本次只修正文档真源。

## 是否向后兼容

是。该变更不改变运行时代码，只同步架构文档与当前实现。
