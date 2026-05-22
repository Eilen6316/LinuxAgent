# Plan C：Codex-style request lifecycle and runtime event model

## 状态

本文件是 2026-05-19 重开的 Plan C 索引。旧 Plan C（自动批量参数收集向导）
已经完成并从 `.work/plan/` 移除；历史决策保留在 `.work/change/`。

本轮 Plan C 学习 `/codex` 的请求生命周期设计，但不复制其具体实现。LinuxAgent
要吸收的是 typed turn、typed event、active/history 分离、可取消 runtime、
pending input/request、按需上下文和可观察并发任务。

## 总目标

把 LinuxAgent 的一次用户请求收敛为清晰、可取消、可恢复、可观察的运行时生命周期：

```text
TurnStarted -> typed events / typed requests -> TurnCompleted | TurnAborted
```

完成后，UI 不再通过猜测文本、覆盖终端输出或保留临时 loading 行来表达进度；
core/app/UI 之间通过稳定事件和 request 协议协作。模型仍保持自由规划，Python
只承载协议、状态机、安全边界和展示边界。

## 设计底线

- 不通过 runbook、Python 关键词表或固定自然语言触发器限制 AI 行为。
- 不把业务答案、技术方案、澄清问题、子 agent 使用策略写死在 Python。
- 不改变 R-SEC / R-HITL 红线；命令执行仍经过 policy、sandbox、HITL 和 audit。
- 不让 UI 直接理解 graph 内部状态；UI 消费 typed runtime events / pending requests。
- 不让 core 依赖终端渲染细节；core 只产生协议对象。
- 不把 telemetry event 直接混入 HITL audit schema；改变 audit schema 必须另写 change。
- 不翻译或固定 LLM 生成内容；i18n 只处理 LinuxAgent 自有固定可见文本。
- 测试优先断言结构化事件、状态和 schema，不断言长段文案。

## 子计划顺序

| Plan | 主题 | 目标层级 | 实施边界 |
|---|---|---:|---|
| [C1](PlanC1.md) | Runtime inventory and vocabulary | P0 | 盘点现状与命名，不改行为 |
| [C2](PlanC2.md) | Typed event schema | P0 | 新增 DTO/schema/adapter，不改 UI |
| [C3](PlanC3.md) | Event sink and legacy bridge | P0 | 统一事件出口，兼容旧 dict event |
| [C4](PlanC4.md) | Turn lifecycle envelope | P0 | App/GraphRuntime 边界发 turn 事件 |
| [C5](PlanC5.md) | Work item event protocol | P0/P1 | 工具、命令、worker、阶段统一 item 事件 |
| [C6](PlanC6.md) | Active view state reducer | P0 | 事件归约为 active state，不碰 Rich 渲染 |
| [C7](PlanC7.md) | Terminal renderer integration | P0 | UI 消费 active state，解决覆盖和闪屏 |
| [C8](PlanC8.md) | History consolidation | P0/P3 | turn 结束后收口临时进度 |
| [C9](PlanC9.md) | Unified cancellation controller | P0 | Esc 贯穿 turn/model/tool/job |
| [C10](PlanC10.md) | Pending input / steer queue | P0 | 忙碌输入排队，不绕过 HITL |
| [C11](PlanC11.md) | Pending request base protocol | P1/P2 | 审批、提问、权限请求统一 request |
| [C12](PlanC12.md) | Existing approval migration | P1/P2 | confirm/patch/resume 适配 pending request |
| [C13](PlanC13.md) | Model-initiated user input request | P1 | AI 主动提问能力，不靠 slash command |
| [C14](PlanC14.md) | Tool runtime typed observability | P1/P2 | 工具 started/delta/completed/failed/cancelled |
| [C15](PlanC15.md) | Tool concurrency and resource locks | P2 | 只读并发、写操作串行或资源锁 |
| [C16](PlanC16.md) | On-demand LinuxAgent manual | P1/P3 | 能力说明书按需加载 |
| [C17](PlanC17.md) | On-demand context injection | P2/P3 | AGENTS/说明书/环境摘要按需进上下文 |
| [C18](PlanC18.md) | Replayable event stream and resume | P2 | 从事件/状态恢复 pending request |
| [C19](PlanC19.md) | Worker/subagent/progress events | P1/P3 | 并发任务与子 agent 可观察 |
| [C20](PlanC20.md) | Event-based harness and final gates | P2/P3 | 测试从文案转为事件，最终验收 |

## 实施节奏

- 每个子计划独立完成、验证、提交；不要跨多个子计划大包提交。
- 如果实现时发现现有代码已经覆盖某个子计划，只补 schema、边界测试或文档，不重写。
- 如果某个子计划需要调整边界，先更新对应 `PlanC*.md`，必要时追加 `.work/change/`。
- 子计划完成记录写在对应文件末尾；Plan C 总索引只记录整体状态。

## 阶段门

### Phase 1：P0 lifecycle gate（C1-C10）

C1-C10 是第一阶段独立验收门。只有当 typed event、turn lifecycle、work item、
active/history、取消骨架和 pending input 都跑通后，才进入 C11+ 的 request、
tool runtime、context 和 replay 深水区。

Phase 1 必须证明：

- 每个 turn 都有 start/end/abort 事件。
- active view 由事件 reducer 驱动，renderer 有最小消费者验证。
- turn 结束后临时进度能收口到 history。
- cancellation token 骨架已经进入 turn envelope，Esc 不再依赖长轮询。
- pending input 不会绕过 HITL pending request。

Phase 1 收口记录：

- 2026-05-19：C1-C10 已按独立子计划完成并提交，覆盖 commit
  `9356950` → `fec1aed`。对应能力包括 runtime vocabulary、typed event schema、
  event sink、turn lifecycle envelope、work item protocol、active view reducer、
  terminal renderer integration、history consolidation、unified cancellation
  controller 和 pending input queue。各子计划完成记录中列出的单元测试、`make type`、
  `make lint`、`make security`、`make test` 已在对应实施轮次执行；后续 C20 仍需把
  Phase 1 gate 纳入 harness 结构化事件验收。

### Phase 2：request/tool/context/replay（C11-C20）

C11-C20 在 Phase 1 通过后推进。若用户能力说明书问题仍是高频真实痛点，
C16/C17 可以在 C14/C15 前实施，但必须先更新本索引和相关子计划，不按临场判断
硬跳。

Phase 2 内部依赖：

- C13 依赖 C11 的 pending request 基协议和 request type 预留。
- C15 依赖 C14 的 typed tool runtime events。
- C18 依赖 C11/C12，至少 pending request schema 与 legacy migration 已稳定。
- C19 依赖 C5 的 work item 协议；若要展示工具/worker 细节，应等 C14 的 tool
  events 稳定后再实施。
- C20 是集成验收，不得提前替代 C1-C19 的局部测试。

## 关键风险控制

- C2 必须预留 context event family，供 C16/C17 的 on-demand manual/context
  injection 使用，避免后期补 schema 返工。
- C4 必须引入 cancellation controller/token 的最小骨架；C9 再完成模型、tool、
  worker、后台任务的深度传播。
- C6 必须提供 `ActiveTurnView` 最小消费者或 fake renderer 验证；C7 若要求改
  snapshot 形状，必须回到 C6 更新接口和测试。
- C11 必须产出 interrupt-to-request/request-type 映射表，并给 C13 的
  `request_user_input` 类新增 request type 留位；C12 迁移期间必须 legacy
  payload 与 pending request 双跑兼容。
- C20 必须把 Phase 1 gate 和最终 gate 都转成结构化事件/状态断言，不能靠中文或
  英文长文案判断。

## Done Definition

Plan C 全部完成必须同时满足：

- 请求生命周期具备 typed turn / typed event / typed request 协议。
- UI active view 与 history consolidation 分离。
- Esc 取消贯穿 turn、模型调用、tool runtime 和长任务。
- pending input / pending request 可恢复，不绕过 HITL。
- 工具 runtime 统一处理取消、超时、并发能力、输出流、脱敏和 telemetry。
- LinuxAgent 说明书和上下文按需注入，不每轮进入 prompt。
- worker/subagent/progress 有结构化事件，用户能看到并发工作内容。
- harness 和单元测试基于结构事件而非文案。
- 不新增硬编码业务判断规则。
- `make lint`
- `make type`
- `make security`
- `make test`
- `make harness`
