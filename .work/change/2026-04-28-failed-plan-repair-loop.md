# 失败计划自动修复循环

- **日期**：2026-04-28
- **类型**：设计变更
- **影响范围**：Graph 路由、CommandPlan 失败恢复、交互命令识别
- **决策者**：用户

## 背景

多步骤计划虽然已经能顺序执行所有原始步骤，但当计划中的命令本身写错或不适合无 shell 执行环境时，Graph 会在计划耗尽后进入分析并结束当前 turn。用户要求不能在任务未完成时直接结束，应根据失败结果继续排查并生成修复命令，直到完成或由人类干预停止。

MySQL 场景还暴露出另一个问题：`mysql -e ...` 属于非交互批处理命令，但策略把所有 `mysql` 都标记为 `INTERACTIVE`，导致执行结果无法被正常捕获。

## 新决策

当当前 `CommandPlan` 已耗尽且本轮计划结果包含非零退出码时，Graph 进入 `repair_plan` 节点。该节点把原始用户目标和失败命令结果交给 LLM，要求返回后续修复 `CommandPlan`，再继续走统一的 safety / HITL / execute 流程。每个修复命令仍需要策略检查和必要的人类确认；用户拒绝确认即停止。

为避免旧失败导致修复成功后继续重复重规划，状态中记录 `plan_result_start_index`，只检查当前计划对应的执行结果。

`mysql`、`psql` 等交互客户端在带 `-e`、`--execute`、`-B`、`--batch` 等非交互标志时，不再按 `INTERACTIVE` 执行。

## 影响

- **受影响文档**：
  - `prompts/system.md`
- **受影响代码**：
  - `src/linuxagent/graph/replanning.py`
  - `src/linuxagent/graph/agent_graph.py`
  - `src/linuxagent/graph/routing.py`
  - `src/linuxagent/graph/state.py`
  - `src/linuxagent/graph/nodes.py`
  - `src/linuxagent/graph/intent.py`
  - `src/linuxagent/policy/engine.py`

## 是否向后兼容

是。成功计划仍直接分析并结束；失败计划会继续请求修复命令，且所有命令仍受现有策略和 HITL 保护。
