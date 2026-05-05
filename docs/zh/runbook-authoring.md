# Runbook 编写指南

Runbook 是给 planner 的结构化运维经验，不是关键词路由，也不会绕过
policy / HITL / audit。内置 runbook 位于 `runbooks/`。

## 适合新增 Runbook 的场景

- 磁盘、内存、CPU、负载等只读诊断
- systemd 服务状态和最近日志
- 端口占用和监听进程
- OS、包版本、证书状态
- 容器状态排查

不建议把生产变更类流程做成默认 runbook。变更命令应该继续由模型生成结构化
计划，并经过明确的人机确认。

## 基本结构

以现有 `runbooks/*.yaml` 为准。典型只读 runbook：

```yaml
id: service-status
title: Service status inspection
description: Inspect a systemd service without mutating it.
steps:
  - command: systemctl status nginx --no-pager
    purpose: Show service state and recent status output.
    read_only: true
  - command: journalctl -u nginx --no-pager -n 100
    purpose: Show recent service logs.
    read_only: true
```

## 安全要求

- 优先只读命令。
- 加 `--no-pager` 等非交互参数。
- 避免 shell operator、重定向、管道、命令替换和 glob。
- 不写真实密钥、私有主机名或私有 IP。
- 示例 IP 使用文档保留网段：`192.0.2.0/24`、`198.51.100.0/24`、
  `203.0.113.0/24`。
- `read_only: true` 的步骤在加载时必须被 policy 判定为 `SAFE`。

## 验证

```bash
make test
make harness
make security
```

安全相关测试不要 mock policy engine 的核心判断。
