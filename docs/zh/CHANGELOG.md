# 更新日志

LinuxAgent 的重要变更记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)。
版本遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Fixed

- Audit hash-chain append 现在会在读取尾部 hash 到写入新记录的整个过程持有文件锁，
  避免多个 LinuxAgent 进程同时写入 `~/.linuxagent/audit.log` 时破坏链条。
- Audit append 现在从 JSONL 日志尾部读取上一条 hash，不再每次写入都全量扫描
  审计日志。
- LLM 可见工具现在会在 catalog metadata 缺失或非法时 fail closed，返回结构化
  denied tool event，而不是把未包装工具绑定进 provider tool loop。
- Workspace tool 错误现在会显示为简短的操作员可读消息，包含 tool 名称、目标和
  人类可读原因，不再把内部 JSON 错误结构直接打到终端。
- Runtime activity 输出现在会抑制相邻重复进度行，同时继续保留完整 telemetry 事件。
- 命令确认现在会保留并展示 inline interpreter 和 LOLBin 命令的完整 policy
  details，包括全部 matched rules、capabilities、risk score 和策略白名单决定。
- 命令确认现在会把 inline interpreter payload 提取成带行号的独立审阅块，并明确标记
  被截断的 command 或 payload，使较长的 `python3 -c` 和 shell `-c` 请求在批准前可审阅。
- `python3 -c`、`bash -c` 等 inline interpreter 命令不再走继承 stdio 的
  interactive 执行路径。流式输出会写入 `ExecutionResult.stdout`/`stderr`，
  并进入命令结果面板和分析 prompt。
- 历史消息里如果存在未配对的 assistant tool call，下一次 provider 请求前会插入结构化、
  已脱敏的 tool error，避免 provider 因消息格式不完整崩溃，同时不会执行任何工具。

### Changed

- 新增运行时 i18n 顶层配置 `language`（`zh-CN` / `en-US`），用于 LinuxAgent 自有
  的固定 CLI/TUI 文案、slash help、确认/阻断消息、诊断信息和内置展示元数据。prompt
  模板、模型可见指导、LLM 最终回答、审计 JSON 字段、MCP 协议字段、tool name 和
  policy id 都保持稳定，不做本地化。
- build/security 门禁现在会校验 locale catalog parity、打包后的 locale 可加载性，
  以及未登记的中文运行时字符串字面量。英文 phrase 扫描仍是 report-only，避免把协议
  字符串和模型可见文本误判为必须翻译。
- 轻量 learner / 推荐辅助模块内部从 `linuxagent.intelligence` 改名为
  `linuxagent.usage_insights`；旧 import path 继续作为兼容重导出，`intelligence`
  配置键不变。
- SSH 执行现在使用由 manager 持有的 worker pool，并通过 `cluster.max_workers`
  控制并发数，不再每条远程命令创建一次单 worker pool。
- Policy 规则和对话权限现在支持结构化 argv 形状匹配，包括精确前缀、token 位置
  和带值 flag，单次批准不会泛化到插入参数或重排参数后的命令形态。
- 新增应用级 `network` 策略基础，用于后续 LLM/web 工具；默认拒绝，支持域名
  allow/deny、network decision 审计记录，并会在 `linuxagent check` 中展示摘要。
- 源码 checkout 的 bootstrap 现在会初始化
  `~/.config/linuxagent/config.yaml`，并安装用户级
  `~/.local/bin/linuxagent` 启动器；用户无需激活项目 venv，也能在任意目录启动
  LinuxAgent。
- LLM 可见工具现在共用统一 runtime budget：单工具超时、单工具输出上限、单次请求
  累计输出预算和最大 tool-calling 轮数。Runtime event 会记录已脱敏的 args/output
  preview、sandbox metadata、状态、输出长度和截断信息。
- 可选的 embedding-backed intelligence tools 不再按 provider 默认暴露；需要推荐、
  知识库和语义相似命令工具时，显式设置 `intelligence.tools_enabled: true`。
- 新增统一 tool catalog，供运行时 tool binding、`/tools` 上下文、product context
  和 `linuxagent check` 复用；check 输出现在会展示每个 tool 的 sandbox profile、
  permissions、network access、HITL mode、allowed roots 和 runner isolation note。
- 新增 `prompts/manifest/` operating manifest，用渐进披露方式提供 LinuxAgent
  全方位说明。Direct-answer 路径可以获得完整产品运行上下文，普通运维规划仍只接收
  简短 product context。
- 直接回答、intent router 和规划 prompt 现在会收到简洁的 LinuxAgent 产品上下文，
  覆盖 `/resume`、会话历史、checkpoint、learner memory 边界以及当前
  provider/model 来源，使自身能力类问题回答更准确。
- LinuxAgent 自身能力类问题现在会进入 operating manifest 直接回答路径；cache、
  memory、tool、safety、resume、network boundary 等回答来自同一份可维护的自身
  说明书，而不是散落在 prompt 里的专项规则。
- Slash command 帮助和补全现在共用同一个命令目录。
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
- Planner 和 repair prompt 现在会引导静态文件或脚本创建优先使用 `FilePatchPlan`；
  只有确实需要运行时输出时才保留短小、可审阅的 inline interpreter 命令。

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
