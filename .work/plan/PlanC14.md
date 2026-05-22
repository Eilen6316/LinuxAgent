# Plan C14：Tool runtime typed observability

## 目标

将所有 LLM-visible tool 的运行状态统一发 typed work item events，包括 started、
delta、completed、failed、cancelled、timeout。工具 runtime 同时负责输出预算、
脱敏和 telemetry/audit 边界。

## 范围

- 复用现有 sandbox/tool runtime，不新增绕过路径。
- typed event 覆盖 tool name、args preview、sandbox profile、duration、status。
- args 和 output preview 必须脱敏。
- 支持同步 tool 在线程或安全执行器中超时/取消，不阻塞事件循环。

## 不做

- 不改变具体工具业务逻辑。
- 不把完整工具输出无节制塞进 UI 或 prompt。
- 不把 telemetry event 当成 HITL audit 替代品。

## 实施步骤

1. 找到统一 tool invocation 边界。
2. 在边界发 tool item started/completed/failed/cancelled。
3. 为同步工具补安全超时路径。
4. 将 args/output preview 通过统一 redaction。
5. 保留 audit 记录，并与 runtime event 明确分层。

## 测试/验证

- 单元测试覆盖同步 tool timeout。
- 单元测试覆盖 args/output 脱敏。
- 单元测试覆盖 failed/cancelled event。
- 安全测试覆盖 LLM-visible tool 必须附带 sandbox metadata。

## 验收

- UI 可以看到每个工具调用的真实状态。
- tool timeout 不被同步阻塞吞掉。
- 敏感参数不会出现在 runtime event 明文中。

## 完成记录

- 2026-05-19：完成 tool runtime typed observability。
- 提交：`c5234be` (`runtime: add typed tool events`)。
- 实施摘要：
  - 新增/扩展 `runtime_events.tool_work_item_event()`，以 typed work item 表达 tool
    completed/failed/cancelled 等状态，包含 turn/thread 关联、tool 名称、args preview、
    sandbox 与结果摘要。
  - `graph/tool_loop.py` 在统一 tool loop 边界发出 typed tool event。
  - `GraphRuntime` 注入 turn context，planner/file patch repair/provider tool loop 均可
    关联当前 turn。
  - `tools/sandbox.py` 和 provider 层保留既有 sandbox、timeout、output budget 和脱敏边界。
- 验证：
  - `tests/unit/graph/test_tool_loop.py`
  - `tests/unit/graph/test_runtime.py`
  - `tests/unit/providers/test_base.py`
  - `tests/unit/tools/test_tool_sandbox.py`
