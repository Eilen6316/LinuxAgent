# SSH 远程执行语义安全化

- **日期**：2026-04-26
- **类型**：设计变更 + 实施记录
- **影响范围**：`src/linuxagent/cluster/`、`src/linuxagent/graph/`、测试 harness、README
- **决策者**：项目所有者 + Codex

## 背景

本地执行已经通过 argv/subprocess 路径避免 `shell=True`，但 Paramiko `exec_command(command)` 会把字符串交给远端用户 shell。即使命令已经经过 policy/HITL，远程路径仍可能出现 `;`、管道、重定向、命令替换等 shell 语义差异。

## 新决策

1. 新增远程命令准入层，远程命令必须可由 `shlex.split` 解析为简单 argv。
2. 默认拒绝远程 shell 元字符和操作符：`;`、`|`、`&&`、`||`、重定向、命令替换、变量展开等。
3. Graph 在命令选中远程 host 后先执行远程准入检查，失败时直接 `BLOCK`，不进入确认和执行。
4. SSHManager 仍保留同样校验，防止绕过 graph 的直接服务调用。
5. 这是保守策略：部分本地安全的 shell 风格命令在远程路径会被拒绝，用户应拆成单条简单命令或后续通过受控 remote runner 执行。

## 是否向后兼容

部分不兼容：此前可远程发送的 shell 组合命令现在会被拒绝。这是有意收紧，避免远程 shell 语义扩大安全边界。
