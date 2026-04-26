# 生产就绪清单

LinuxAgent v4.0.0 适合受控的人机协同运维场景，不应被当作无人值守自动修复器。

## 适合的场景

- 在开发、预发和受控生产主机上做交互式诊断。
- 以读取为主的操作：服务状态、端口、磁盘、日志、负载、容器检查。
- SSH 目标已登记在 `known_hosts` 中的 fan-out 操作。
- 需要审计的故障排查，由操作员批准每个敏感步骤。
- 团队能够在扩大使用前 review 并调优策略规则。

## 没有额外控制时不适合

- 完全自主修复。
- 默认以 root 运行。
- 期望命令确认自动通过的 cron 或 CI 任务。
- 命令输出不能离开主机，且没有配置本地模型路径的环境。
- 未登记 host key 的未知 SSH 主机或临时主机。
- 本地用户不可信的多租户终端环境。

## 上生产前检查

- [ ] 已安装 Python 3.11 或 3.12。
- [ ] `config.yaml` 归操作员所有，权限为 `chmod 600`。
- [ ] API provider、model、base URL 和 timeout 已显式 review。
- [ ] 已 review 当前环境的 runtime policy overrides。
- [ ] SSH 目标已登记到 `~/.ssh/known_hosts`。
- [ ] audit log 路径位于持久本地存储。
- [ ] 事故复盘流程包含 `linuxagent audit verify`。
- [ ] 操作员知道 `--yes` 不会绕过命令级确认。
- [ ] 高影响工作流已编码为 YAML runbook，并覆盖 harness 场景。
- [ ] 部署的 release artifact 已通过 `make verify-build`。

## Release 验证

源码 checkout：

```bash
make lint
make type
make test
make security
make harness
make verify-build
```

已安装 wheel：

```bash
linuxagent --help
linuxagent check
linuxagent audit verify
```

## 运维护栏

- 首轮推广优先使用只读 prompt。
- 先在小主机组验证，再扩大集群操作范围。
- 生产环境保持较低批量确认阈值。
- 审批时查看 `matched_rule`、`risk_score` 和 `capabilities`。
- 被 BLOCK 的命令应视作策略反馈，不应绕过。

## 已知限制

- 审计日志是本地文件；如果需要集中留存，请接入自己的日志管道。
- 操作员批准后，项目不会对命令做沙箱隔离。
- LLM 分析可能出错；它是总结辅助，不是事实源。
- Anthropic provider 是可选能力，需要安装 extra 依赖。
- 不支持 Windows。
