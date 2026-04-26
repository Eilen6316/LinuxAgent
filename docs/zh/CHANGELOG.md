# 更新日志

LinuxAgent 的重要变更记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)。
版本遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Added

- 新增通用系统健康 Runbook，用于“查看服务器状态”类请求，覆盖 uptime、
  内存、文件系统使用率和 failed systemd units。
- 新增软件包清单和操作系统版本 Runbook，覆盖常见本机诊断请求。
- 新增直接回答 Prompt 路径，用于能力说明类对话问题，避免为非执行回答生成
  `echo` 命令和 HITL 确认。
- 新增面向终端的分析 Prompt，要求模型输出纯文本总结，避免 Markdown 格式影响阅读。

### Fixed

- 当带工具的计划生成返回自然语言而不是严格 JSON `CommandPlan` 时，会无工具重试一次。
- `localhost` / `本机` 一类 `CommandPlan.target_hosts` 保持本地执行，不再误走
  未解析的 SSH 集群目标。
- DeepSeek 默认不再启用依赖 embedding 的 intelligence tools，除非显式配置。
- LLM 多命令计划现在会在每一步成功后继续执行后续计划步骤，不再第一条命令后提前结束。

## [4.0.0] - 2026-04-26

LinuxAgent v4.0.0 是重写后的第一个正式版本。它用基于 LangGraph 的、
策略驱动、可审计 CLI 替代旧原型，定位为受控的人机协同 Linux 运维工具。

### Added

- LangGraph 状态机，包含 parse、policy、confirm、execute、analyze 阶段。
- 能力驱动策略引擎，输出 `SAFE`、`CONFIRM`、`BLOCK`、risk score、
  capabilities、matched rules，并支持 runtime YAML policy override。
- 策略评估前校验结构化 JSON `CommandPlan`。
- 8 个 YAML runbook，覆盖常见运维诊断；支持多步骤编排和逐步策略检查。
- SSH 集群执行，包含批量确认、host-key 验证和远程 shell 语法防护。
- `~/.linuxagent/audit.log` hash-chained JSONL 审计日志，以及
  `linuxagent audit verify`。
- LLM 分析路径前的输出脱敏和 tool result guard。
- 带 trace ID 的本地 telemetry JSONL spans。
- CPU、内存、根文件系统资源阈值告警。
- 单元、集成、安全、类型、lint、harness、可选 provider 和 wheel 安装验证门禁。
- 公开项目治理文件：`SECURITY.md` / `docs/zh/SECURITY.md`、
  `CONTRIBUTING.md` / `docs/zh/CONTRIBUTING.md`、行为准则、Issue/PR 模板。
- v3 到 v4 迁移指南、威胁模型、生产就绪清单和正式 release notes。
- `constraints.txt` 可复现安装约束。

### Changed

- 包元数据从开发 Alpha 收口为 v4.0.0 stable release。
- 配置使用 Pydantic v2 fail-fast 校验，用户配置要求当前用户所有且 `chmod 600`。
- 密钥只通过 `config.yaml` 配置；`.env` 不承载密钥值。
- README、PyPI 元信息、CHANGELOG 和 release notes 统一 v4.0.0 版本叙事。
- CI 发布 coverage artifact，并验证 wheel 内置配置、prompt 和 runbook 数据。

### Removed

- 冻结的 v3 代码路径不再作为 active package 的一部分。
- `setup.py` 和临时依赖文件由 `pyproject.toml` 与 release constraints 替代。

### Security

- CI 红线阻断 `shell=True`、`AutoAddPolicy`、裸 `except:` 和 graph node 内
  `input()`。
- LLM 生成命令首次使用必须确认。
- 破坏性命令永不进入会话白名单。
- 非 TTY 确认请求自动拒绝。
- SSH 集群模式在执行前阻断命令串联、重定向、命令替换和变量展开。
- Tool 输出进入 LLM tool loop 前会脱敏和 guard。

### Migration

本版本不能从 v3 原地平滑升级。参见
[docs/zh/migration-v3-to-v4.md](migration-v3-to-v4.md)。

[Unreleased]: https://github.com/Eilen6316/LinuxAgent/compare/v4.0.0...HEAD
[4.0.0]: https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0
