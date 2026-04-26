# Plan 11 · SSH 远程执行语义安全化

**目标**：收紧 Paramiko `exec_command()` 的远程 shell 语义，避免本地无 shell 执行与远程 shell 执行之间出现安全落差。

**前置条件**：Plan10 完成。

**交付物**：远程命令准入层 + SSH/cluster 接入 + 单元测试与 harness 场景。

---

## Scope

- 新增远程命令准入模块，使用 `shlex.split` 解析并拒绝远程 shell 元字符
- `SSHManager.execute_many()` 在连接任何主机前 fail-fast 校验远程命令
- Graph 在选中远程 host 后，对不满足远程准入的命令直接 `BLOCK`
- 保留 SSHManager 层防线，避免绕过 graph 的服务调用直接发送 shell 语法
- README / docs 明确本地执行与远程 SSH 执行的安全边界差异

## 验收标准

- [x] `echo ok; whoami` 这类远程 shell 序列在集群路径进入 `BLOCK`
- [x] `echo ok; rm -rf /` 不会触发任何 SSH 连接
- [x] 简单 argv 命令（如 `uptime` / `systemctl status nginx --no-pager`）仍可远程执行
- [x] SSH 层和 Graph 层均有测试
- [x] 现有 HITL / cluster harness 仍通过，并新增远程 shell 语义场景

<!-- 完成记录（完成后追加） -->

## 完成记录

- **日期**：2026-04-26
- **实现 commit**：`85724c7`
- **验证**：`make test`（228 passed, 1 skipped, coverage 87.27%）、`make lint`、`make type`、`make security`、`make harness`
- **偏差清单**：
  - 本轮采用保守的远程 shell 语法拒绝策略；复杂 shell 管道需要拆成简单远程命令，或后续引入受控 remote runner。
