# Plan 12 · Runbook 接入 Graph 主流程

**目标**：让经过测试的 YAML Runbook 在 LLM 生成命令前优先参与意图解析，降低命令幻觉。

**前置条件**：Plan11 完成。

**交付物**：GraphDependencies 接入 RunbookEngine + runbook-to-CommandPlan 转换 + harness 场景。

---

## Scope

- `Container` 构建默认 `RunbookEngine`
- `parse_intent` 优先匹配 runbook，命中后转换为标准 `CommandPlan`
- runbook step 继续经过 policy / HITL / execute / audit，不绕过安全路径
- 确认 payload 展示 runbook id/title 和后续步骤
- 新增 runbook harness 场景，覆盖磁盘 runbook 主流程

## 验收标准

- [ ] 命中 runbook 时不调用 LLM 生成命令
- [ ] runbook 生成的命令仍触发 `LLM_FIRST_RUN` 确认
- [ ] 确认 payload 包含 runbook id/title/steps
- [ ] harness 新增 runbook 场景并通过
- [ ] 现有 HITL / SSH / policy 门禁仍通过

<!-- 完成记录（完成后追加） -->
