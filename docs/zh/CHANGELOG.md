# 更新日志

LinuxAgent 的重要变更记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)。
版本遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Fixed

- `python3 -c`、`bash -c` 等 inline interpreter 命令不再走继承 stdio 的
  interactive 执行路径。流式输出会写入 `ExecutionResult.stdout`/`stderr`，
  并进入命令结果面板和分析 prompt。

### Changed

- 新增 `linuxagent audit summary` 和 `linuxagent audit inspect` 只读审计诊断，
  可查看决策统计、safety 统计、hash-chain 状态和脱敏后的近期命令明细。
- MCP runbook 摘要现在包含显式 step count 和摘要级 safety posture，同时继续
  隐藏原始命令字符串。
- Workspace tool 活动现在会展示来自 `read_file`、`list_dir` 和
  `search_files` 完成结果的简短 evidence 摘要。文件修改流程返回“无需修改”时，
  最终回答也会附带引用到的依据，方便操作员看到模型基于哪些文件行或搜索结果做判断。
- File patch repair 现在会更严格地基于当前文件快照重建 diff；模型把 JSON 包在解释性文字
  或代码块里时也能提取有效 JSON；目标文件快照较大时，终端失败信息会截断展示，避免刷屏。
- 历史对话类问题现在会稳定走直接回答路径，不再误入命令或文件计划流程，避免纯聊天请求暴露
  内部的 no-change evidence 校验错误。
- `read_file` 的 workspace evidence 预览现在来自同一份实际发给 agent 的限流输出；
  对较长读取窗口会同时展示开头和末尾，避免只显示文件头造成误导。

## [4.1.0] - 2026-05-07

### Added

- 新增通用系统健康 Runbook，用于“查看服务器状态”类请求，覆盖 uptime、
  内存、文件系统使用率和 failed systemd units。
- 新增软件包清单和操作系统版本 Runbook，覆盖常见本机诊断请求。
- 新增直接回答 Prompt 路径，用于能力说明类对话问题，避免为非执行回答生成
  `echo` 命令和 HITL 确认。
- 新增面向终端的分析 Prompt，要求模型输出纯文本总结，避免 Markdown 格式影响阅读。
- 新增红队攻击策略 harness，覆盖 24 个命令 agent 攻击用例。
- 新增 shell 结构策略分析，覆盖 pipeline、subshell、command substitution、
  redirect 和嵌套 shell 执行。
- 新增确定性 LOLBin 与 interpreter escape 检测，覆盖 network-to-shell
  pipeline、`find -exec`、`xargs`、`awk system()`、编辑器 shell escape 和
  interpreter inline execution。
- 新增面向 shell 结构解析的 Hypothesis fuzzing。
- 新增 policy 延迟 benchmark 报告，包含 P50/P95/P99 指标。
- 新增可选 HTTP audit sink，保持本地先追加审计语义，并把 sink 投递失败记录回本地审计链。
- 新增 telemetry exporter 模式：local JSONL、console、OTLP HTTP JSON 和 none。
- 新增 Landlock sandbox 设计文档，覆盖能力探测、降级顺序、兼容性限制和实现切分。
- 新增只读 stdio MCP server prototype，仅暴露 policy classify 与 audit verify，
  不暴露命令执行能力。

### Fixed

- 当带工具的计划生成返回自然语言而不是严格 JSON `CommandPlan` 时，会无工具重试一次。
- `CommandPlan.target_hosts` 改为结构化远程目标来源：空列表表示本地，
  `["*"]` 表示所有已配置集群主机。
- DeepSeek 默认不再启用依赖 embedding 的 intelligence tools，除非显式配置。
- LLM 多命令计划现在会在每一步成功后继续执行后续计划步骤，不再第一条命令后提前结束。

### Changed

- README 将已完成的安全深度工作整理成对外项目叙事，而不只散落在实现计划中。
- Release workflow 改为按 tag 名选择 release notes，不再硬编码 v4.0.0 发布正文。

## [4.0.0] - 2026-04-26

LinuxAgent v4.0.0 是重写后的第一个正式版本。它用基于 LangGraph 的、
策略驱动、可审计 CLI 替代旧原型，定位为受控的人机协同 Linux 运维工具。

### Added

- LangGraph 状态机，包含 parse、policy、confirm、execute、analyze 阶段。
- 能力驱动策略引擎，输出 `SAFE`、`CONFIRM`、`BLOCK`、risk score、
  capabilities、matched rules，并支持 runtime YAML policy override。
- 策略评估前校验结构化 JSON `CommandPlan`。
- 11 个 YAML runbook，作为 planner guidance 覆盖常见运维诊断；支持多步骤计划和逐步策略检查。
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

[Unreleased]: https://github.com/Eilen6316/LinuxAgent/compare/v4.1.0...HEAD
[4.1.0]: https://github.com/Eilen6316/LinuxAgent/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0
