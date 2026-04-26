# 安全政策

LinuxAgent 会执行由 LLM 工作流提议的 Linux 命令。涉及命令执行、SSH 行为、
审计完整性、配置密钥或输出脱敏的问题都会按高优先级处理。

## 支持版本

| 版本 | 是否支持 |
|---|---|
| 4.0.x | 是 |
| 3.x 及更早版本 | 否 |

## 报告漏洞

请不要通过公开 issue 报告疑似安全漏洞。

推荐报告路径：

1. 如果仓库启用了 GitHub private vulnerability reporting，请优先使用它。
2. 如果不可用，请通过仓库所有者主页联系维护者，并在标题中注明
   `LinuxAgent security report`。

请包含：

- 问题简述，以及受影响的版本或 commit。
- 复现步骤，包括相关命令或 prompt。
- 预期影响：命令绕过、密钥泄露、审计篡改、SSH 信任问题、拒绝服务等。
- 已脱敏的日志或输出。

## 响应目标

| 严重级别 | 示例 | 目标 |
|---|---|---|
| Critical | 静默执行命令、绕过 HITL、任意破坏性执行 | 48 小时内初始响应 |
| High | 密钥泄露到 LLM/tool 输出、SSH host-key 绕过、审计哈希链绕过 | 72 小时内初始响应 |
| Medium | BLOCK/CONFIRM 分类错误、本地权限弱点 | 7 天内初始响应 |
| Low | 文档或加固缺口，利用面有限 | 尽力处理 |

## 安全边界

LinuxAgent 是一个需要人工确认的运维助手，不是命令沙箱。项目假设：

- 本地操作员可信，负责批准或拒绝操作。
- `config.yaml` 位于本地，归当前用户所有，且权限为 `chmod 600`。
- 默认不信任未知 SSH 主机。
- 命令会以调用 LinuxAgent 的用户权限执行。

参见 [威胁模型](threat-model.md) 和 [生产就绪清单](production-readiness.md)。
