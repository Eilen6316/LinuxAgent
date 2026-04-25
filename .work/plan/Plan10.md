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

- [x] 默认不要求外部 OTel 服务
- [x] 每次 HITL / command execution 有 trace_id
- [x] audit hash chain 可验证并能定位篡改行
- [x] `linuxagent audit verify` 有单元测试和 CLI 测试
- [x] CI 增加 audit verify 测试

<!-- 完成记录（完成后追加） -->

## 完成记录

- **日期**：2026-04-26
- **实现 commit**：`5f4b840`
- **验证**：`make test`（217 passed, 1 skipped, coverage 87.13%）、`make lint`、`make type`、`make security`、`make harness`
- **偏差清单**：
  - OTLP exporter 本轮作为配置字段预留；默认实现为本地 JSONL recorder，未引入新的外部 exporter 依赖。
  - “CI 增加 audit verify 测试”通过默认 `make test` 中的 CLI/unit 测试覆盖；未新增单独 GitHub Actions job。
