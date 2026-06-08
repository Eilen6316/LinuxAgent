# LinuxAgent Documentation

This directory contains the long-form manuals, release notes, migration notes,
and production guidance that are intentionally kept out of the root project
homepage.

## Manuals

| Document | Purpose |
|---|---|
| [English manual](en/README.md) | Full installation, configuration, usage, and architecture overview |
| [中文完整文档](zh/README.md) | 中文安装、配置、使用和架构说明 |
| [自动参数收集向导](zh/auto-wizard.md) | 中文自动 wizard 触发、交互、恢复和安全边界说明 |
| [Quick Start](en/quickstart.md) | Short installation and first-run walkthrough |
| [Development Guide](en/development.md) | Local development and test workflow |
| [中文开发指南](zh/development.md) | 中文本地开发流程和架构稳定性门禁 |
| [TypeScript v5 Experimental Kernel](en/typescript-v5.md) | Status, boundaries, and commands for the experimental TS rewrite track |
| [TypeScript v5 实验内核](zh/typescript-v5.md) | TS 实验重写线的状态、边界和开发命令 |
| [Provider Matrix](en/provider-matrix.md) | Supported provider paths, token parameters, and compatibility report format |
| [Provider 兼容矩阵](zh/provider-matrix.md) | 中文 provider 兼容路径和反馈格式 |
| [Red Team Baseline](en/red-team.md) | Adversarial policy test baseline and xfail semantics |
| [Policy Benchmark](../benchmarks/policy-benchmark.md) | Policy/parser latency P50/P95/P99 report |
| [Landlock Sandbox Design](design/sandbox-landlock.md) | Planned kernel-native sandbox backend design and compatibility matrix |
| [MCP Server Design](design/mcp-server.md) | Read-only MCP server prototype, threat model, and future execution boundary |
| [Roadmap](../ROADMAP.md) | Maintainer priorities and good-first-issue areas |
| [Why substring matching is not safety](../blog.md) | Opinionated technical essay on LLM command-agent safety |
| [Real User Feedback](https://github.com/Eilen6316/LinuxAgent/issues/new?template=user_feedback.yml) | Share concrete usage feedback from a real machine |

## Release And Operations

| Document | Purpose |
|---|---|
| [Release Guide](en/release.md) | Release checklist, constraints, artifacts, and GitHub About copy |
| [中文发布指南](zh/release.md) | 中文发布流程 |
| [v4.1.0 Release Notes](releases/v4.1.0.md) | English release notes |
| [v4.1.0 中文发布说明](zh/releases/v4.1.0.md) | 中文发布说明 |
| [v4.0.0 Release Notes](releases/v4.0.0.md) | English release notes |
| [v4.0.0 中文发布说明](zh/releases/v4.0.0.md) | 中文发布说明 |
| [Migration Guide](en/migration-v3-to-v4.md) | v3 to v4 breaking changes |
| [v3 到 v4 迁移指南](zh/migration-v3-to-v4.md) | 中文迁移指南 |

## Security And Production

| Document | Purpose |
|---|---|
| [Threat Model](en/threat-model.md) | Assets, trust boundaries, mitigations, and out-of-scope items |
| [Operator Safety Model](en/operator-safety.md) | Plain-language command approval, sandbox, audit, and unsuitable-use guidance |
| [操作员安全模型](zh/operator-safety.md) | 中文安全边界说明 |
| [威胁模型](zh/threat-model.md) | 中文威胁模型 |
| [Production Readiness](en/production-readiness.md) | Suitable uses, unsuitable cases, and rollout checklist |
| [生产就绪清单](zh/production-readiness.md) | 中文生产就绪清单 |
| [中文安全政策](zh/SECURITY.md) | Chinese companion to root `SECURITY.md` |
| [中文贡献指南](zh/CONTRIBUTING.md) | Chinese companion to root `CONTRIBUTING.md` |
| [中文行为准则](zh/CODE_OF_CONDUCT.md) | Chinese companion to root `CODE_OF_CONDUCT.md` |
| [中文更新日志](zh/CHANGELOG.md) | Chinese companion to root `CHANGELOG.md` |
