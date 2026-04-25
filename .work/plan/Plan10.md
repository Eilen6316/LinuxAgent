# Plan 10 · 可观测性与防篡改审计

**目标**：让每次 Agent 决策链路可追踪、可排障、可验证审计完整性。

**前置条件**：Plan9 完成。

**交付物**：telemetry spans + hash-chained audit + audit verify CLI。

---

## Scope

- 为 `llm.complete`、`policy.evaluate`、`hitl.confirm`、`command.execute`、`ssh.execute`、`runbook.step` 增加可选 telemetry span
- 默认本地 JSONL telemetry，不依赖外部服务；OTLP exporter 作为可选配置
- audit log 增加 `prev_hash` / `hash`，形成防篡改链
- 新增 `linuxagent audit verify` 校验当前审计日志完整性
- audit 记录关联 `trace_id`

## 验收标准

- [ ] 默认不要求外部 OTel 服务
- [ ] 每次 HITL / command execution 有 trace_id
- [ ] audit hash chain 可验证并能定位篡改行
- [ ] `linuxagent audit verify` 有单元测试和 CLI 测试
- [ ] CI 增加 audit verify 测试

<!-- 完成记录（完成后追加） -->
