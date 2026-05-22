# Plan C11：Pending request base protocol

## 目标

建立统一 pending request 协议。命令确认、文件 patch 确认、权限请求、AI 主动提问、
未来的选择器或表单，都通过同一种 request lifecycle 表示。

## 范围

- 定义 `request_started`、`request_updated`、`request_resolved`、`request_cancelled`。
- 定义 request 字段：`request_id`、`turn_id`、`request_type`、`payload`、
  `status`、`resumable`、`expires`、`result`。
- request payload 必须可序列化、可脱敏、可用于 resume。
- UI dispatcher 按 request type 分发，不由 app loop 到处写判断。
- 产出 interrupt-to-request/request-type 映射表，至少包含：legacy payload type、
  pending request type、UI handler、resume input schema、audit decision event、
  fallback。
- 映射表必须同时包含 legacy migration rows 和新增 request rows。新增 request rows
  至少为 C13 的 `request_user_input` / model-initiated question 类 request type
  留位，即使 C13 尚未实现。

## 不做

- 不改变具体审批策略。
- 不新增默认通过。
- 不把业务问题写死为 request 模板。

## 实施步骤

1. 在 typed event schema 中补 pending request 模型。
2. 定义 request store 或 turn state 中的 pending request 表示。
3. 产出 request 与 LangGraph interrupt 的映射表，并写入本计划完成记录或开发文档。
4. 为 UI 层定义通用 dispatcher 接口。
5. 为非 TTY 定义 fail-closed 行为。

## 测试/验证

- 单元测试覆盖 request 序列化和恢复。
- 单元测试覆盖非 TTY fail-closed。
- 单元测试覆盖 unknown request type 的安全 fallback。
- 单元测试覆盖映射表中的每类 legacy payload 都能转换为 pending request。
- 单元测试覆盖新增 request type 留位不会被 unknown fallback 误拒。

## 验收

- 后续所有人机交互都能复用同一 pending request 协议。
- request id 稳定，可用于 resume 和 audit 关联。
- UI 不需要理解 graph 内部节点名。
- C12 可以按映射表迁移，不需要重新决定 payload 到 UI/resume 的关系。
- C13 可以直接复用 C11 预留的 model-initiated input request type。

## 完成记录

- 2026-05-19：完成 pending request 基础协议。
- 提交：`368865d` (`runtime lifecycle: define pending request protocol`)。
- 实施摘要：
  - 新增 `src/linuxagent/pending_request.py`，定义 pending request status/type、
    `PendingRequest`、request result、request lifecycle event 和
    `PENDING_REQUEST_MAPPINGS`。
  - 新增 `src/linuxagent/ui/request_dispatcher.py`，为 UI handler 提供按 request
    type 分发的通用入口。
  - `active_view` 可消费 pending request event，并将当前等待 request 纳入 active
    snapshot。
  - 映射表包含 legacy confirm/file patch/wizard/permission payload 与
    `request_user_input` 预留行。
- 验证：
  - `tests/unit/test_pending_request.py`
  - `tests/unit/test_active_view.py`
