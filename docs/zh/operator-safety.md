# 操作员安全模型

LinuxAgent 是 HITL-first 的 Linux 运维控制面，不是无人值守 shell chatbot。
模型可以规划和解释，但执行权限始终由确定性的 policy、人机确认、审计和 SSH
边界控制。

## 模型可以做什么

- 通过 prompt 判断意图
- 生成结构化 `CommandPlan`
- 生成结构化 `FilePatchPlan`
- 调用已包装、限时、限输出、会脱敏的工具
- 对脱敏后的执行结果做总结

## 模型不能直接做什么

- 绕过 sandbox runner 创建本地进程
- 跳过 policy
- 跳过 LLM 首次命令确认
- 创建全局命令白名单
- 自动信任未知 SSH host key
- 绕过 FilePatchPlan 和确认直接写文件

## 确认菜单语义

| 选项 | 含义 |
|---|---|
| `Yes` | 只批准本次操作 |
| `Yes, don't ask again` | 仅在当前 conversation thread 和同一 `/resume` thread 中允许匹配命令 |
| `No` | 拒绝本次操作 |

对话权限不适用于破坏性命令、`never_whitelist` 规则、SSH 批量确认或新对话。

## Sandbox 边界

默认 `sandbox.enabled: false` 且 `runner: noop`，只记录 metadata，不提供进程隔离。
启用安全 profile 后，如果 runner 无法执行对应隔离能力，默认 fail closed。

SSH 远端命令不受本地 OS sandbox 保护。远端边界来自 host-key 校验、目标主机
范围、低权限账号、远端工作目录、sudo allowlist、批量确认和审计。

## 审计与脱敏

HITL 决策和执行结果写入 `0o600` hash-chained audit log。命令原文为了可追溯
会保留；其他结构化字段和进入模型上下文的输出会尽力脱敏。

不要主动让 LinuxAgent 打印密钥。脱敏是防御层，不是暴露凭据的许可。
