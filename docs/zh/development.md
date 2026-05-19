# 开发

## 架构稳定性预算

`make security` 和 CI 会运行 `scripts/check_architecture_budget.py`。这个门禁把
架构稳定化工作变成可执行约束：

- `src/linuxagent/app/agent.py` 保持 300 个物理行以内。
- `graph/` 模块默认保持 430 个物理行以内。当前仍偏大的模块使用窄范围单文件上限，
  只锁住现状；继续增长时需要先拆分。
- 安全敏感的 `plans/` 模块默认保持 260 个物理行以内，现有公开计划模型门面有单文件上限。
- 所有 Python 函数保持 50 个物理行以内。
- 新增 `AgentState` 字段必须同步写入 `graph/state_contracts.py` 的所有权分区。
- 新增 graph node factory 必须加入预算覆盖清单，并指向真实的单元测试和 harness 或边界场景。

LLM 可见工具的 `ToolSandboxSpec` 元数据、以及 subprocess 只能由 sandbox runner 拥有，
由同一个 security gate 中的 `scripts/check_sandbox_rules.py` 继续强制检查。

## 运行时生命周期词汇

LinuxAgent 的运行时体验改造统一使用以下词汇：

| 术语 | 含义 | 当前所有者 |
|---|---|---|
| turn | 一个用户请求在一个 graph thread/checkpoint 中的一次处理 | `src/linuxagent/app/agent.py`, `src/linuxagent/graph/runtime.py` |
| runtime event | turn 或工具运行期间发出的结构化非审计状态信号 | `src/linuxagent/graph/events.py`, `src/linuxagent/runtime_events.py` |
| tool event | LLM 可见工具和 provider tool loop 发出的工具运行事件 | `src/linuxagent/providers/base.py`, `src/linuxagent/tools/sandbox.py` |
| work item | 一个用户可见的运行单元，例如命令、工具调用、worker 或后台任务 | 当前为 dict event，typed model 待落地 |
| pending request | 可恢复的人类决策或输入请求，当前主要由 LangGraph interrupt 表示 | `src/linuxagent/graph/*confirm*.py`, `src/linuxagent/ui/interrupt_dispatcher.py` |
| active view | turn 运行中终端临时展示的状态 | `src/linuxagent/ui/working_status.py` |
| history | active view 清理或收口后的持久对话输出 | chat history 和 graph messages |
| steer input | turn 仍在运行时用户继续输入的内容 | 尚未一等建模 |
| cancellation token | 一个运行中 turn 及其子任务共享的取消状态 | 尚未一等建模 |

当前 runtime event 仍是 legacy dict。Graph 节点通过 `notify_event()` 发出高层
`activity` 事件；只读批处理和直接回答 worker 通过 `src/linuxagent/runtime_events.py`
发出 `worker_group` 事件。命令批次、后台任务、命令输出流使用相关 dict event，
由 app runtime observer 消费。

runtime event 当前有三个消费者：

- telemetry：`src/linuxagent/app/runtime_telemetry.py` 将部分事件写为本地 telemetry span。
- UI activity：`src/linuxagent/app/runtime_messages.py`、`src/linuxagent/container.py`
  和 `src/linuxagent/ui/working_status.py` 将事件渲染成终端临时状态。
- harness：`tests/harness/runner.py` 收集 `runtime_events` 和 `tool_events` 做场景断言。

tool event 目前独立于 runtime event。container 会通过 `AuditLog.record_tool_event()`
记录工具审计元数据，同时渲染临时 UI activity。工具参数和输出 preview 到达 telemetry、
UI 或模型上下文前必须保持脱敏。

audit record 不是 runtime event。HITL 决策、命令执行审计、文件 patch 审计和工具审计
仍是持久安全记录，保留自己的 schema 和保留策略。runtime event 只服务 UI、telemetry
和未来 replay，不替代 audit。

typed lifecycle 落地前的已知缺口：

- 还没有 typed `turn_started` / `turn_completed` / `turn_aborted` envelope。
- active terminal state 直接由消息渲染，而不是来自纯 active-view reducer。
- 取消能力存在于 graph invocation/UI 边界，但还不是共享 runtime token。
- 忙碌时的用户输入和 pending human request 还没有统一队列或 request protocol。
- harness event assertion 仍观察 legacy dict event，而不是稳定 typed event contract。

Phase 1 lifecycle gate 的 harness 场景和事件断言应使用这组词汇命名，测试协议状态，
不要测试中英文 UI 长文案。
