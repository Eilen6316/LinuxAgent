# 把 Human-in-the-Loop 提升为一等原则

- **日期**：2026-04-23
- **类型**：设计变更
- **影响范围**：`rule/baseline.md`（新增 R-HITL 章节）、`design/architecture.md`（新增 D-9 + `audit.py`）、`plan/Plan1.md`（配置模型）、`plan/Plan2.md`（§2.5 来源升级）、`plan/Plan4.md`（§4.1a confirm 节点）、`plan/Plan6.md`（HITL harness 场景）、`CLAUDE.md` / `AGENTS.md`（红线表）
- **决策者**：项目所有者

## 背景

初版 `.work/` 把 Human-in-the-Loop 隐式埋在 Plan 4 的 `safety_check → confirm_node` 流程图里：

- 没有规则条款强制"LLM 输出默认不可信"
- `confirm_node` 的实现语义不清（同步 `input()`? `prompt_async()`? LangGraph `interrupt()`?）
- 集群批量操作没有强制确认阈值
- `--yes` 的降级范围未定义，可能被用成关闭安全拦截的开关
- 无审计留痕，事后无法复盘人工决策
- 无非交互（无 TTY / `--batch`）场景的安全默认

作为 Linux 运维 Agent，这些缺口是上线级风险。本次变更把 HITL 从"Plan 4 里的一个节点"升格为贯穿**规则层 / 架构层 / 计划层 / 测试层**的原则。

## 新决策

### 1. 规则层：新增 R-HITL 章节（`rule/baseline.md`）

六条不可妥协规则：

| ID | 要点 |
|---|---|
| R-HITL-01 | LLM 输出默认不可信：LLM 生成的命令首次必须 CONFIRM；会话级白名单是唯一降级路径，进程退出即失效，不持久化 |
| R-HITL-02 | 批量操作（`cluster.batch_confirm_threshold` 默认 `2`）强制确认，不受 `--yes` / 白名单影响 |
| R-HITL-03 | `DESTRUCTIVE_PATTERNS` 命中的命令永不进白名单，每次都 CONFIRM |
| R-HITL-04 | `--yes` 仅对对话级无副作用确认生效；非交互环境下 CONFIRM = 拒绝（`non_tty_auto_deny`） |
| R-HITL-05 | confirm 节点**必须**用 `langgraph.types.interrupt()`；图节点内禁 `input()` / `prompt_async()` |
| R-HITL-06 | 所有 HITL 事件（请求 + 决策 + 执行）追加到 `~/.linuxagent/audit.log`（JSONL，`0o600`，不轮转） |

### 2. 架构层：新增 D-9（`design/architecture.md`）

- 六原则 + confirm 节点骨架代码
- 前端适配矩阵：CLI / LangGraph Studio / `--batch` / 未来 Web，全部走同一 `interrupt()` 协议
- 目录树新增 `src/linuxagent/audit.py`

### 3. 命令来源升级表（Plan 2 §2.5）

`SafetyResult` 新增 `command_source` 字段。`is_safe()` 的级别按来源单向升级：

| 来源 | SAFE | CONFIRM | BLOCK |
|---|---|---|---|
| `user` | SAFE | CONFIRM | BLOCK |
| `llm`（首次） | **→ CONFIRM** | CONFIRM | BLOCK |
| `whitelist` | SAFE | CONFIRM | BLOCK |
| 任意 + 破坏性模式 | **→ CONFIRM（不进白名单）** | CONFIRM | BLOCK |

`DESTRUCTIVE_PATTERNS` 在 `executors/safety.py` 定义；修改清单需走 `change/`。

### 4. confirm 节点实现（Plan 4 §4.1a）

- `interrupt()` 原语 + `MemorySaver` 持久化 → 中断可恢复
- CLI 前端通过 `Command(resume={...})` 恢复，无 TTY 自动返回 `non_tty_auto_deny`
- 新增 `src/linuxagent/audit.py`：`AuditLog.begin` / `record_decision` / `record_execution`，asyncio 锁保护，`_redact` 脱敏已知密钥字段（不脱敏命令原文）
- 审计不可关闭（配置模型无 `enabled` 字段）

### 5. 配置模型新增（Plan 1 §1.2）

| 新增模型 / 字段 | 默认值 |
|---|---|
| `ClusterConfig.batch_confirm_threshold` | `2` |
| `SecurityConfig.session_whitelist_enabled` | `true` |
| `AuditConfig.path` | `~/.linuxagent/audit.log` |

### 6. Harness 场景（Plan 6 §6.3）

新增 7 个 HITL 场景覆盖 R-HITL-01 到 R-HITL-06；场景文件格式扩展 `expected_interrupts` + `resume` + `tty` + `audit_log_contains` 字段。

### 7. 红线表（`CLAUDE.md` / `AGENTS.md`）

摘要表增加 R-HITL-01/03/05/06 四条（选择 HITL 中最容易被机械违反、最影响安全的条款）。

## 影响

- **受影响文档**：见上述各小节
- **受影响代码**：尚未实现（影响 Plan 1 / 2 / 4 / 6 的实施）

## 是否向后兼容

**否** —— 本次变更为 v4 重写增加新的架构约束，无存量实现。完成后的 Agent 行为与 v3（静默执行 LLM 命令）不兼容，这是预期的安全升级。
