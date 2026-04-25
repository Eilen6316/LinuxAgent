# Plan 9 · 结构化 CommandPlan 与 YAML Runbook

**目标**：从“LLM 输出一条命令”升级为“LLM 输出结构化计划，优先匹配经过测试的 Runbook”。

**前置条件**：Plan8 完成。

**交付物**：`src/linuxagent/plans/` + `src/linuxagent/runbooks/` + YAML runbook scenarios。

---

## Scope

- 新增 `CommandPlan` / `PlannedCommand` Pydantic 模型
- LLM 字段只作为建议；每条命令最终仍由 policy engine 判定
- Graph 拆为 `plan_intent -> policy_evaluate -> preflight -> confirm -> execute -> verify -> analyze`
- 新增 YAML Runbook 引擎，优先支持磁盘、端口、服务、日志、证书、内存、负载、容器 8 类场景
- mutation 步骤必须确认；read-only 步骤可在策略允许下自动执行

## 验收标准

- [ ] LLM 非 JSON / schema 错误 fail-fast，不执行命令
- [ ] Runbook 步骤全部过 policy engine
- [ ] 每个 Runbook 至少 3 个 harness 场景
- [ ] 确认面板展示目标、预检、风险、验证、回滚
- [ ] 现有 basic/dangerous/HITL harness 仍通过

<!-- 完成记录（完成后追加） -->
