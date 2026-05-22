# Plan C13：Model-initiated user input request

## 目标

提供模型主动向用户提问的结构化能力，类似 `request_user_input`。当模型无法完全理解
需求或需要用户选择/补充时，可发起 pending request；不再依赖显式 slash command。

## 范围

- 新增 LLM-visible 工具或 graph capability，用于发起用户输入 request。
- 复用 C11 预留的 model-initiated user input request type，不在 C13 临时发明第二套命名。
- 支持多问题、多选、自由文本等结构，但问题内容由模型生成。
- UI 一次性展示完整 request，用户可在提交前切换和修改。
- 非交互环境 fail closed，并把需要补充的信息返回给模型。

## 不做

- 不写死“技术栈选型”等业务问题。
- 不规定模型什么时候必须提问。
- 不用 slash command 作为主入口。
- 不绕过普通直接回答能力；模型可选择直接答或提问。
- 不绕过 C11 pending request protocol。

## 实施步骤

1. 设计 request payload：问题、选项、可选自由文本、默认值、提交状态。
2. 将能力暴露给模型，但 prompt 只说明能力和边界，不写固定流程。
3. UI dispatcher 接入用户输入 request。
4. 将用户提交结果作为结构化上下文返回 planner/respond。
5. 增加 loop guard，避免同一 turn 反复弹相同 request。

## 测试/验证

- 单元测试覆盖 request payload 验证。
- UI 测试覆盖多问题一次提交和修改。
- graph 测试覆盖模型发起 request 后 resume。
- 非 TTY 测试覆盖 fail-closed。
- C20 final gate 必须覆盖 model-initiated user input request 的事件序列。

## 验收

- 用户提到模糊需求时，模型可以自主弹出交互请求。
- 交互框不会一题一题提前结束。
- 代码中没有硬编码业务问题或固定触发词。

## 完成记录

- 2026-05-19：完成 model-initiated user input request。
- 提交：`4d55ef4` (`runtime: add model input requests`)。
- 实施摘要：
  - 新增 `src/linuxagent/user_input.py`，定义模型发起用户输入 request 的问题、选项、
    answer、result、wizard bridge 和校验逻辑。
  - 新增 `graph/user_input_nodes.py` 与 `graph/user_input_routing.py`，将
    `IntentMode.REQUEST_USER_INPUT` 接入 graph routing/resume。
  - 更新 `prompts/intent_router.md`，向模型暴露结构化提问能力和边界，不写死业务问题。
  - UI 新增 `user_input_interrupt` 展示与提交流程；非交互/取消路径保持 fail-closed。
  - 增加 loop guard 和 terminal restore 支持，避免同一 turn 反复弹相同 request。
- 验证：
  - `tests/unit/test_user_input.py`
  - `tests/unit/graph/test_agent_graph.py`
  - `tests/unit/graph/test_intent_router.py`
  - `tests/unit/ui/test_interrupt_dispatcher.py`
  - `tests/unit/ui/test_terminal_restore.py`
