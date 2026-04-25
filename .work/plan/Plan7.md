# Plan 7 · 隐私脱敏与输出保护

**目标**：阻止敏感信息在 LLM 分析、工具调用、审计日志、prompt history 中外泄。

**前置条件**：Plan1-Plan6 完成。

**交付物**：`src/linuxagent/security/` + graph/analyze 输出保护 + tool 文件读取 allowlist + prompt history 权限加固。

---

## Scope

### 7.1 Redaction 核心

新增 `src/linuxagent/security/redaction.py`：
- 文本脱敏：API key、Authorization header、常见 token、password 字段、数据库 DSN、私钥块
- record 脱敏：递归处理 dict/list，对敏感 key 的值替换为 `***redacted***`
- 返回脱敏计数，供输出保护和 UI 预览使用

### 7.2 输出保护

新增 `src/linuxagent/security/output_guard.py`：
- `ExecutionResult` 进入 LLM 之前必须先脱敏
- stdout/stderr 合并文本有最大字符数上限，默认 8000
- 被截断时显式标记 `truncated=true`

### 7.3 Tool 读取沙箱

`search_logs(pattern, log_file)`：
- 默认只允许读取配置声明的日志根目录（默认 `/var/log`）
- 禁止读取 allowlist 外路径
- 文件大小超限拒绝
- 匹配行返回前先脱敏

### 7.4 审计与本地历史

- `AuditLog.append()` 写入前递归脱敏敏感字段
- `ConsoleUI` 的 prompt history 文件强制 `0o600`

## 测试要求

- redaction 单测覆盖常见 token、连接串、Authorization、私钥块
- graph 单测验证 LLM 分析只收到 redacted output
- system tool 单测验证 allowlist 外路径被拒绝
- audit 单测验证敏感 key 被脱敏
- prompt history 权限单测验证 `0o600`

## 验收标准

- [x] `make test` 通过且覆盖率 ≥80%
- [x] `make lint` / `make type` / `make security` 通过
- [x] `make harness` 通过
- [x] `search_logs` 不再可读取 allowlist 外文件
- [x] `analyze_result_node` 不再把原始 stdout/stderr 发给 LLM
- [x] audit record 中敏感字段脱敏，command 原文本身保持可追溯

<!-- 完成记录（完成后追加） -->

## 完成记录

- **日期**：2026-04-25
- **实现 commit**：`aec137a`
- **偏差清单**：
  - 未新增 harness YAML 场景；Plan7 风险点通过单元测试覆盖，现有 harness 全量通过。
  - `search_logs` allowlist 当前由 `log_analysis.default_log_paths` 的父目录推导，后续如需独立配置可在 Plan8 policy 配置中统一收口。
