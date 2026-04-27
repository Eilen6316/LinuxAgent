# 日常聊天直答分流

- **日期**：2026-04-28
- **类型**：设计变更
- **影响范围**：Graph intent parsing、HITL 触发条件
- **决策者**：用户

## 背景

此前 `parse_intent` 除少数能力问题外，默认要求模型返回 `CommandPlan`。这会让普通解释、闲聊、how-to 问题也进入命令计划路径，并在确认面板中展示 `Command / Goal / Purpose / Safety / Rule / Source / Risk / Preflight / Verify / Rollback` 等执行字段。

## 新决策

在 `parse_intent` 前置 LLM 意图路由：

- 运行时先调用 `prompts/intent_router.md`，由模型返回 `DIRECT_ANSWER` / `COMMAND_PLAN` / `CLARIFY`。
- `DIRECT_ANSWER` 和 `CLARIFY` 直接输出模型给出的文本，不生成 `pending_command`，因此不会触发 HITL 确认面板。
- `COMMAND_PLAN` 才进入现有 CommandPlan / policy / HITL / execute 流程。
- Python 中禁止维护意图关键词表；路由判断由 prompt + 模型承担。

## 影响

- **受影响文档**：无
- **受影响代码**：
  - `prompts/intent_router.md`
  - `src/linuxagent/prompts_loader.py`
  - `src/linuxagent/graph/intent.py`
  - `tests/unit/graph/test_agent_graph.py`

## 是否向后兼容

是。实际操作请求仍走原有 policy / HITL；普通聊天减少不必要的确认面板。
