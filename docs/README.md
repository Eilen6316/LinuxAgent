# LinuxAgent Documentation

This directory contains the long-form manuals, release notes, migration notes,
and production guidance that are intentionally kept out of the root project
homepage. Use this page as a task-oriented map; paired English and Chinese
documents are listed together where both exist.

## Quick Start

- **First run:** [Quick Start](en/quickstart.md) / [中文快速开始](zh/quickstart.md)
- **Full manual:** [English manual](en/README.md) / [中文手册](zh/README.md)
- **Auto parameter wizard:** [自动参数收集向导](zh/auto-wizard.md)

## Safety

- **Operator safety:** [Operator Safety Model](en/operator-safety.md) / [操作员安全模型](zh/operator-safety.md)
- **Threat model:** [Threat Model](en/threat-model.md) / [威胁模型](zh/threat-model.md)
- **Production rollout:** [Production Readiness](en/production-readiness.md) / [生产就绪清单](zh/production-readiness.md)
- **Security policy:** [SECURITY.md](../SECURITY.md) / [中文安全政策](zh/SECURITY.md)
- **Red-team baseline:** [Red Team Baseline](en/red-team.md)

## Configuration and Providers

- **Provider setup:** [Provider Matrix](en/provider-matrix.md) / [Provider 兼容矩阵](zh/provider-matrix.md)
- **Configuration examples:** [default.yaml](../configs/default.yaml), [example.yaml](../configs/example.yaml)
- **Policy configuration:** [policy.default.yaml](../configs/policy.default.yaml)
- **Migration:** [Migration Guide](en/migration-v3-to-v4.md) / [v3 到 v4 迁移指南](zh/migration-v3-to-v4.md)

## User Guides

- **Roadmap:** [Roadmap](../ROADMAP.md)
- **Safety essay:** [Why substring matching is not safety](../blog.md)
- **Feedback:** [Real User Feedback](https://github.com/Eilen6316/LinuxAgent/issues/new?template=user_feedback.yml)

## Development

- **Development workflow:** [Development Guide](en/development.md) / [中文开发指南](zh/development.md)
- **Policy performance:** [Policy Benchmark](../benchmarks/policy-benchmark.md)
- **Skills reference:** [Skills](skills.md)
- **Project governance:** [中文贡献指南](zh/CONTRIBUTING.md), [中文行为准则](zh/CODE_OF_CONDUCT.md), [中文更新日志](zh/CHANGELOG.md)

## TypeScript/Design/Release

- **TypeScript v5 track:** [TypeScript v5 Experimental Kernel](en/typescript-v5.md) / [TypeScript v5 实验内核](zh/typescript-v5.md)
- **TypeScript rewrite design:** [TypeScript v5 Progressive Rewrite Design](design/typescript-v5-progressive-rewrite.md)
- **Design notes:** [Landlock Sandbox](design/sandbox-landlock.md), [MCP Server](design/mcp-server.md), [TS SSH Library Decision](design/ts-ssh-library-decision.md)
- **Release process:** [Release Guide](en/release.md) / [中文发布指南](zh/release.md)
- **Release notes:** [vNext](releases/vNext.md), [v4.1.0](releases/v4.1.0.md) / [中文](zh/releases/v4.1.0.md), [v4.0.0](releases/v4.0.0.md) / [中文](zh/releases/v4.0.0.md)
