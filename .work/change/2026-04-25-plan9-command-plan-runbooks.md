# Plan9 CommandPlan 与 Runbook 实施范围

- **日期**：2026-04-25
- **类型**：设计变更 + 实施记录
- **影响范围**：`.work/plan/Plan9.md`、`src/linuxagent/plans/`、`src/linuxagent/runbooks/`、`src/linuxagent/graph/`
- **决策者**：项目所有者 + Codex

## 背景

Plan9 要求从“LLM 输出一条命令”升级为结构化 `CommandPlan`，并新增 YAML Runbook 引擎。当前 graph 的 `parse_intent_node` 接受裸命令文本，测试和 harness 也都使用裸命令 fake response。

## 新决策

1. `parse_intent_node` 改为严格解析 JSON `CommandPlan`；非 JSON / schema 错误进入 `BLOCK`，不执行命令。
2. 为保持安全边界，每条计划里的命令仍通过 Plan8 policy engine 判定；LLM 标注的 `read_only` 仅作为展示/计划信息，不作为放行依据。
3. Graph 本轮执行计划中的第一条主命令；preflight / verification / rollback 先进入 state 和确认 payload 展示，不自动执行。完整多步骤执行循环留给后续增强。
4. 新增 `src/linuxagent/runbooks/` 和 `runbooks/*.yaml`，提供 8 类高频运维 Runbook 的结构化定义、加载、匹配、policy 校验。
5. 现有 fake provider / harness 响应迁移为 JSON plan，验证 strict parsing 不破坏 HITL、批量确认和审计流程。

## 影响

- **受影响文档**：
  - `.work/plan/Plan9.md`
- **受影响代码**：
  - `src/linuxagent/plans/`
  - `src/linuxagent/runbooks/`
  - `src/linuxagent/graph/state.py`
  - `src/linuxagent/graph/nodes.py`
  - `src/linuxagent/ui/console.py`
  - `runbooks/`

## 是否向后兼容

部分不兼容：LLM provider 现在必须返回 JSON `CommandPlan`。这是 Plan9 的显式目标；测试和 prompt 会同步迁移。CLI 用户输入行为不变。
