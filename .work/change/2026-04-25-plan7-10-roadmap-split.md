# 拆分 Plan7-Plan10 后续路线图

- **日期**：2026-04-25
- **类型**：偏离计划 + 文档整理
- **影响范围**：`.work/README.md`、`.work/plan/Plan7.md`-`Plan10.md`、`src/linuxagent/security/`
- **决策者**：项目所有者 + Codex

## 背景

当前 `design/architecture.md` 已提出从“安全 CLI”升级为“带策略、回滚、观测、Runbook 的可控运维 Agent”，但 `.work/plan/` 为空，无法作为后续实施入口。

同时 code review 发现当前实现中存在两个优先级高于策略引擎的生产安全短板：
- LLM tool path 可通过 `search_logs` 在 HITL 前读取任意本地文件
- `analyze_result_node` 会把命令 stdout/stderr 原样发给 LLM

## 新决策

1. 将后续路线拆为 Plan7-Plan10：
   - Plan7：隐私脱敏、输出保护、工具读取沙箱
   - Plan8：能力驱动的策略引擎
   - Plan9：结构化 CommandPlan 与 YAML Runbook
   - Plan10：可观测性与防篡改审计
2. 先实施 Plan7，再进入策略引擎。理由是当前已有真实数据外泄风险，必须先收紧 LLM 可见数据和工具权限边界。
3. MCP / 高级 UI 暂不进入 Plan7-10 的第一批实现，待 Plan8-10 稳定后再规划。

## 影响

- **受影响文档**：
  - `.work/README.md`
  - `.work/plan/Plan7.md`-`Plan10.md`
- **受影响代码**：
  - `src/linuxagent/security/`
  - `src/linuxagent/graph/nodes.py`
  - `src/linuxagent/tools/system_tools.py`
  - `src/linuxagent/audit.py`
  - `src/linuxagent/ui/console.py`

## 是否向后兼容

是。Plan7 默认只收紧数据外发和工具读文件边界；正常命令执行、HITL、配置加载语义不变。
