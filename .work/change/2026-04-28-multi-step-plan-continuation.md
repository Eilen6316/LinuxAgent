# 多步骤计划不得因单步失败提前结束

- **日期**：2026-04-28
- **类型**：设计变更
- **影响范围**：Graph 路由、多步骤 CommandPlan prompt
- **决策者**：用户

## 背景

用户执行“安装 MySQL 并修改密码”这类多目标任务时，当前流程可能在安装步骤执行后直接结束当前对话，后续配置或改密步骤未继续执行。原因是 Graph 在任一命令返回非 0 时直接进入分析节点，即使 `CommandPlan.commands` 中仍有后续步骤。

## 新决策

多步骤 `CommandPlan` 只要还有后续步骤，就继续推进到下一步的 safety / HITL / execute 流程；非 0 退出码会保留在步骤结果中，最终分析时一起呈现。只有计划已耗尽、命令被策略 BLOCK、或用户拒绝 HITL 时，当前 turn 才终止。

Prompt 同步强调多目标请求必须覆盖安装、配置、改密、服务启动和验证等完整结果，不得只停在下载安装。

## 影响

- **受影响文档**：
  - `prompts/system.md`
- **受影响代码**：
  - `src/linuxagent/graph/routing.py`
  - `src/linuxagent/graph/intent.py`
  - `tests/unit/graph/test_agent_graph.py`

## 是否向后兼容

是。单命令计划行为不变；多步骤计划更严格地执行完整计划，仍复用每一步现有 policy 与 HITL。
