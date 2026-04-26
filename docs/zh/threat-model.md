# 威胁模型

LinuxAgent 是一个本地 CLI，可以让 LLM 提议 Linux 运维操作，并在人工批准后
执行命令。核心目标不是把 Linux 命令沙箱化，而是让模型驱动的操作明确、可审查、
可审计。

## 资产

- 本地和远程系统完整性。
- `config.yaml` 中的 API key 和凭据。
- 命令输出、日志、主机名、用户名、IP、路径和生产数据。
- SSH 私钥和 `known_hosts` 信任决策。
- `~/.linuxagent/audit.log` 的审计完整性。
- 操作员意图和审批决策。

## 信任边界

| 边界 | 信任假设 |
|---|---|
| 用户终端 | 本地操作员可信，负责批准或拒绝命令 |
| LLM provider | 不可信，不能接收密钥或拥有最终执行权 |
| 本地子进程 | 以调用用户的权限执行 |
| SSH 目标 | 必须已通过 `known_hosts` 建立信任 |
| 配置文件 | 只有归当前用户所有且 `chmod 600` 时可信 |
| 审计日志 | 通过 hash chain 提供本地防篡改检测 |

## 主要威胁与缓解

| 威胁 | 缓解 |
|---|---|
| Prompt injection 生成危险命令 | token 级策略引擎、来源感知 `LLM_FIRST_RUN`、破坏性命令强制确认 |
| 用户误批大范围批量执行 | 主机数达到阈值时强制批量确认 |
| LLM 输出通过引号或 shell 语法绕过安全检查 | `shlex` token facts + 原始字符串 embedded-danger 检测 |
| 远程命令经 shell 特性发生意外展开 | SSH 集群模式阻断命令串联、重定向、命令替换和变量展开 |
| 未知 SSH 主机导致 MITM | 默认 `RejectPolicy` + `load_system_host_keys()` |
| 密钥通过日志或命令输出泄露 | `SecretStr`、配置权限检查、output guard、LLM 路径前脱敏 |
| 篡改审计日志隐藏审批 | hash-chained JSONL + `linuxagent audit verify` |
| 非交互自动化静默批准 | 无 TTY 的确认请求自动拒绝 |
| 依赖过宽带来供应链风险 | 主版本上限 + release constraints + wheel 验证 |

## 不在范围内

- 操作员批准后对任意命令做沙箱隔离。
- 防止恶意本地 root 用户修改文件。
- 替代 HIDS、EDR、SIEM 或特权访问管理。
- 保证 LLM 生成的分析一定正确。
- 保护操作员主动发送给外部 provider 的数据。

## 安全 Review 重点

以下区域的改动需要重点测试和审查：

- `src/linuxagent/policy/`
- `src/linuxagent/executors/`
- `src/linuxagent/cluster/`
- `src/linuxagent/graph/`
- `src/linuxagent/security/`
- `src/linuxagent/audit.py`
- `src/linuxagent/config/`

## 运维建议

- 日常操作使用低权限专用 OS 账号。
- `config.yaml` 保持本地、归操作员所有、权限 `chmod 600`。
- 使用集群功能前，通过带外方式登记 SSH host key。
- 高影响会话后复查 audit log。
- 按环境维护 runtime policy，并在生产使用前用 harness 场景测试。
