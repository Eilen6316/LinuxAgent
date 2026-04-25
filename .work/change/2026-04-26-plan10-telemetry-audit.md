# Plan10 可观测性与防篡改审计实施范围

- **日期**：2026-04-26
- **类型**：设计变更 + 实施记录
- **影响范围**：`.work/plan/Plan10.md`、`src/linuxagent/audit.py`、`src/linuxagent/telemetry.py`、`src/linuxagent/graph/`
- **决策者**：项目所有者 + Codex

## 背景

Plan10 要求增加可观测性 span、审计 hash chain 和 `linuxagent audit verify`。当前审计日志是 append-only JSONL，但没有链式完整性校验，也没有与 graph 决策链路关联的 `trace_id`。

## 新决策

1. 新增本地 JSONL telemetry recorder，默认写入 `~/.linuxagent/telemetry.jsonl`，文件权限 `0o600`，不要求外部 OTel/OTLP 服务。
2. `trace_id` 由 graph 首个节点生成并贯穿 LLM、policy、HITL、command execution 和 audit 记录。
3. audit JSONL 增加 `prev_hash` / `hash`，hash 对脱敏后的 canonical JSON 计算，形成单文件链式完整性校验。
4. 新增 `linuxagent audit verify [--path PATH]`，默认读取 `config.audit.path`，可定位第一条 hash mismatch / prev_hash mismatch / invalid JSON 行。
5. OTLP 仅作为配置字段预留；本轮不引入新的运行时依赖和外部 exporter，避免破坏默认离线可运行能力。

## 影响

- **受影响文档**：
  - `.work/plan/Plan10.md`
  - README / docs
- **受影响代码**：
  - `src/linuxagent/audit.py`
  - `src/linuxagent/telemetry.py`
  - `src/linuxagent/graph/`
  - `src/linuxagent/cli.py`

## 是否向后兼容

是。旧审计 API 调用保持兼容；新写入的 audit log 增加 hash 字段。`audit verify` 对不存在的日志返回 valid，便于新安装环境使用。
