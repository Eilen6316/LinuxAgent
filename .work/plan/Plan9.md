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

- [x] LLM 非 JSON / schema 错误 fail-fast，不执行命令
- [x] Runbook 步骤全部过 policy engine
- [x] 每个 Runbook 至少 3 个 YAML 场景（偏差见完成记录）
- [x] 确认面板展示目标、预检、风险、验证、回滚
- [x] 现有 basic/dangerous/HITL harness 仍通过

<!-- 完成记录（完成后追加） -->

## 完成记录

- **日期**：2026-04-26
- **实现 commit**：`0608a1b`
- **验证**：`make test`（209 passed, 1 skipped, coverage 87.12%）、`make lint`、`make type`、`make security`、`make harness`
- **偏差清单**：
  - Graph 本轮执行 `CommandPlan` 的第一条主命令；`preflight_checks`、`verification_commands`、`rollback_commands` 进入 state 和确认面板，但暂不自动执行多步骤循环。
  - Runbook 已提供 8 个 YAML 文件，每个文件至少 3 个 `scenarios`，并由单元测试校验加载、匹配和 policy 评估；本轮未新增每个 runbook 独立的 harness YAML 场景，因为现有 harness 驱动 graph 流程而非 runbook matcher。
