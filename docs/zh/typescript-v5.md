# TypeScript v5 实验内核

LinuxAgent 当前生产运行时仍是 Python v4。`ts/` 下的 TypeScript v5 工作线是
旁路实验重写：在迁移门禁全部满足前，Python 继续作为行为真源和稳定运行时。

The TypeScript runtime is experimental. Python v4 remains the default release runtime until parity gates pass.

不要把 TypeScript workspace 当成默认 `linuxagent` 运行时。它的作用是让迁移过程
可度量：每个子系统都要带测试、红线检查和与 Python 的 parity fixture，之后才有资格
替换 Python 行为。

## 当前范围

TypeScript workspace 目前包含：

| Package | 当前状态 |
|---|---|
| `@linuxagent/contracts` | Command plan、file patch plan、policy decision、audit entry、runtime event 的共享 TypeBox schema |
| `@linuxagent/policy` | token/effective-command 策略引擎，已覆盖初始 Python fixture parity |
| `@linuxagent/audit` | hash-chained JSONL writer 和 verifier |
| `@linuxagent/sandbox` | sandbox runner contract、noop runner、fail-closed profile selection |
| `@linuxagent/executor` | argv 本地执行器和有界输出脱敏 |
| `@linuxagent/agent-runtime` | 会话权限、审批默认值、tool gate、连接 executor 的 command tool、prompt loader、planner validation、最小 runtime wrapper、tool-result redaction hook、最小 turn runner、remote approval/audit metadata、file patch guards、memory scope model、advisory memory read path 和 pending memory write path |
| `@linuxagent/tui` | 实验 TUI package shell、chat session、direct command routing、approval selector、confirmation renderer 和 slash router |
| `@linuxagent/linuxagent-ts` | 实验 CLI package shell |
| `@linuxagent/ssh` | remote profile validation、remote command guard 和 OpenSSH argv manager |

导出的 parity fixture 位于 `ts/parity/fixtures/`，TS parity CLI runner 位于
`ts/parity/`，TS 红线检查位于 `scripts/check_ts_redlines.mjs`。

## 运行时边界

TS 线沿用 Python v4 的安全规则：

- LLM 计划出的本地命令必须保持 argv 执行，禁止 shell 字符串执行。
- 工具调用必须先经过 LinuxAgent tool gate，再进入执行。
- 安全 sandbox profile 没有可执行 runner 时必须 fail closed。
- noop runner 只能记录 `enforced: false`；普通 `spawn` 不能被当作 sandbox enforcement。
- 命令输出进入模型分析前必须先脱敏并限制长度。
- Prompt 模板继续放在 `prompts/`；TS 代码通过 prompt loader 加载，不把模板硬编码进代码。

当前 TS 代码还没有对外支持的 CLI，也不会替代 `linuxagent`。未来的
`linuxagent-ts` 入口必须保持显式实验状态，直到 policy、HITL、audit、sandbox、SSH、
file patch、output redaction 和 harness parity 都满足对应 release scope。

## 开发命令

从仓库根目录安装依赖并运行 TS 门禁：

```bash
make ts-install
make ts-check
```

可单独运行：

```bash
make ts-lint
make ts-type
make ts-test
make ts-security
make ts-parity
```

`make ts-parity` 运行当前 TS/Python parity runner；目前检查 policy fixture corpus，
并为 audit、harness、red-team parity 输出占位摘要，后续逐步扩展。生产运行时仍以
Python 门禁为准：`make test`、`make security`、`make harness` 和 release 检查仍是
权威门禁。

实验 CLI 的 check 命令只校验显式传入的本地路径，不会调用模型 API：

```bash
node ts/apps/linuxagent-ts/dist/src/cli.js check \
  --config ./config.yaml \
  --policy ./configs/policy.default.yaml \
  --audit ~/.linuxagent/audit.log
```

配置文件必须是私有权限（`chmod 600`）。检查通过返回 `0`，检查失败返回 `1`，
CLI 用法错误返回 `2`。

实验 audit verifier 会调用 TS hash-chain verifier：

```bash
node ts/apps/linuxagent-ts/dist/src/cli.js audit verify ~/.linuxagent/audit.log
```

有效日志返回 `0`，缺失或无效日志返回 `1`。

`linuxagent-ts chat --input <text>` 用来验证实验 TUI 路由面，例如 `/new`、
`/resume` 和 `/tools`。默认 runtime port 仍是安全占位实现，暂不调用 provider。

## 进度表

| 范围 | 状态 |
|---|---|
| Workspace 和红线检查 | 已落地 |
| 共享 contracts 和 Python fixture export | 已落地 |
| policy parity engine | 已覆盖初始 fixture |
| HITL 会话权限、审批默认值、audit hash chain | 已落地 |
| local executor、sandbox contract、output redaction | 已落地 |
| tool gate 连接 executor-backed command tool | 已落地 |
| agent runtime prompt loader | 已落地 |
| planner validation 和 fake model tests | 已落地 |
| 带 sequential command tools 的最小 runtime wrapper | 已落地 |
| tool result analysis/redaction hook | 已落地 |
| 最小 runtime behavior tests | 已落地 |
| 实验 TUI/CLI skeleton | 已落地 |
| `linuxagent-ts check` implementation | 已落地 |
| TUI approval selector 和 confirmation renderer | 已落地 |
| slash router | 已落地 |
| chat loop shell | 已落地 |
| direct command mode | 已落地 |
| SSH library decision | 已落地 |
| remote profile validation | 已落地 |
| remote command guard | 已落地 |
| OpenSSH argv manager | 已落地 |
| SSH approval/audit metadata integration | 已落地 |
| FilePatchPlan contract | 已落地 |
| file patch path policy | 已落地 |
| file patch diff validator | 已落地 |
| file patch transaction guard | 已落地 |
| memory scope model | 已落地 |
| memory read path | 已落地 |
| memory write path pending candidates | 已落地 |
| policy parity CLI runner | 已落地 |
| harness fixture export 和必选场景索引 | 已落地 |
| 实验 TS CI job | 已落地 |
| 完整 file patch writes、harness parity 执行、cutover checklist | 尚未落地 |

后续修改 TS 行为时，同一个小交付里要同步更新本页以及相关 README/development 链接，
确保公开文档和代码状态一致。
