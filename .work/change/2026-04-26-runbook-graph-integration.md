# Runbook 接入 Graph 主流程

- **日期**：2026-04-26
- **类型**：设计变更 + 实施记录
- **影响范围**：`src/linuxagent/graph/`、`src/linuxagent/container.py`、`src/linuxagent/runbooks/`、harness、README
- **决策者**：项目所有者 + Codex

## 背景

Plan9 已提供 Runbook 模型、加载、匹配和 policy 评估，但 Graph 主流程仍完全依赖 LLM 返回 `CommandPlan`。这会让高频运维场景继续暴露在 LLM 命令幻觉风险下。

## 新决策

1. Graph 在调用 LLM 生成命令前先执行 `RunbookEngine.match()`。
2. 命中 runbook 后转换为标准 `CommandPlan`，后续 policy / HITL / execute / audit 路径不分叉。
3. runbook 只作为命令来源优化，不作为安全放行依据；每个 step 仍由 policy engine 校验。
4. 确认 payload 增加 runbook id/title/steps，方便 CLI 展示和未来审计扩展。

## 是否向后兼容

部分行为变化：命中 runbook 的自然语言请求会优先使用内置 runbook 命令，不再调用 LLM 生成命令。这是有意收紧，用经过测试的运维步骤替代自由生成。
