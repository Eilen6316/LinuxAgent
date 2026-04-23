# Plan 4 · LangGraph Agent 编排 + 核心服务层

**目标**：用 LangGraph 状态机替换原 4710 行 God Object，实现可测试、可追踪的 Agent 编排；拆分出独立的 CommandService、ChatService、MonitoringService、ClusterService。

**前置条件**：Plan 2（安全层）、Plan 3（Provider + Graph schema）完成  
**交付物**：`src/linuxagent/graph/`（节点与边实现）+ `src/linuxagent/services/` + `src/linuxagent/app/agent.py`

---

## Scope

### 4.1 LangGraph Agent 图（`graph/agent_graph.py`）

替换原 `agent.py` 的 `process_user_input` 核心流程：

```
┌──────────────┐
│  parse_intent │  ← LLM 理解用户意图，生成候选命令
└──────┬───────┘
       ↓
┌──────────────┐
│ safety_check │  ← CommandExecutor.is_safe()，三级判断
└──────┬───────┘
       ↓ BLOCK         ↓ CONFIRM            ↓ SAFE
   [respond_block]  [confirm_node]      [execute_node]
                         ↓ yes/no
                    [execute_node]
                         ↓
               ┌─────────────────┐
               │  analyze_result │  ← LLM 分析执行结果
               └────────┬────────┘
                        ↓
               ┌─────────────────┐
               │    respond      │  ← 生成用户可读回复
               └────────┬────────┘
                        ↓
                      [END]
```

**关键设计**：
- 每个节点是独立函数，输入/输出为 `AgentState` 的子集
- 条件边（`add_conditional_edges`）替代原版 `if/else` 嵌套
- 递归重试替换为图的循环边（最大 3 次），杜绝调用栈爆炸

```python
graph = StateGraph(AgentState)
graph.add_node("parse_intent", parse_intent_node)
graph.add_node("safety_check", safety_check_node)
graph.add_node("confirm", confirm_node)
graph.add_node("execute", execute_node)
graph.add_node("analyze", analyze_result_node)
graph.add_node("respond", respond_node)

graph.add_conditional_edges(
    "safety_check",
    route_by_safety,
    {"BLOCK": "respond", "CONFIRM": "confirm", "SAFE": "execute"},
)
```

**Checkpointing**：使用 LangGraph `MemorySaver` 持久化对话状态，替换原手写 JSON 历史文件（文件权限问题一并修复：`chmod 0o600`）。Checkpointing 也是 HITL `interrupt()` 的前提（见 §4.1a）。

### 4.1a Human-in-the-Loop 节点实现（R-HITL-01 至 R-HITL-06）

架构原则见 `design/architecture.md` D-9。此处只列实现要点与职责边界。

#### confirm_node：LangGraph interrupt() 原语

```python
# graph/nodes.py
from langgraph.types import interrupt, Command
from langchain_core.messages import AIMessage
from ..audit import AuditLog
from ..executors.safety import is_destructive

async def confirm_node(state: AgentState, *, audit: AuditLog) -> Command:
    audit_id = await audit.begin(
        command=state["pending_command"],
        safety_level=state["safety_level"],
        matched_rule=state.get("matched_rule"),
        command_source=state.get("command_source", "llm"),
        batch_hosts=state.get("batch_hosts", []),
    )
    payload = {
        "type": "confirm_command",
        "audit_id": audit_id,
        "command": state["pending_command"],
        "safety_level": state["safety_level"],
        "matched_rule": state.get("matched_rule"),
        "command_source": state.get("command_source"),
        "batch_hosts": state.get("batch_hosts", []),
        "is_destructive": is_destructive(state["pending_command"]),
    }
    response = interrupt(payload)  # 前端通过 Command(resume=...) 恢复
    decision = response.get("decision", "non_tty_auto_deny")
    await audit.record_decision(
        audit_id,
        decision=decision,
        latency_ms=response.get("latency_ms"),
    )
    if decision != "yes":
        return Command(goto="respond_refused", update={
            "messages": [AIMessage(content=f"已拒绝：{decision}")],
        })
    # 仅 LLM 来源 + 非破坏性 + 非批量 才入白名单（R-HITL-01/02/03）
    if (
        state.get("command_source") == "llm"
        and not payload["is_destructive"]
        and not payload["batch_hosts"]
    ):
        session_whitelist.add(state["pending_command"])
    return Command(goto="execute")
```

**关键约束**：
- `interrupt()` 抛出 `GraphInterrupt`，`MemorySaver` 自动持久化；用户 Ctrl-C 后可通过 `graph.ainvoke(Command(resume={...}), config={"thread_id": ...})` 恢复
- confirm_node **禁止**直接调用 `input()` / `prompt_toolkit` / `click.confirm` —— 那样会把前端耦合进图，违反 R-HITL-05

#### CLI 前端的 interrupt 驱动循环

```python
# app/agent.py（节选）
async def run_turn(self, user_input: str, thread_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    state = {"messages": [HumanMessage(content=user_input)], "command_source": "user"}
    while True:
        result = await self.graph.ainvoke(state, config=config)
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return  # 图走到 END
        # 当前只处理一个中断（confirm_command），多中断聚合留给后续
        intr = interrupts[0]
        response = await self.ui.handle_interrupt(intr.value)
        state = Command(resume=response)
```

`ConsoleUI.handle_interrupt` 负责：
- 无 TTY → 立即返回 `{"decision": "non_tty_auto_deny", "latency_ms": 0}`
- 有 TTY + 批量操作（`batch_hosts`）→ 打印全部主机 + 命令，单次 y/n
- 有 TTY + 非批量 → 打印命令 + safety 信息 + matched_rule，单次 y/n
- 记录从 interrupt 到按键的 `latency_ms`

#### 审计日志（R-HITL-06）

新增 `src/linuxagent/audit.py`：

```python
class AuditLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        self._path = path
        self._lock = asyncio.Lock()

    async def begin(self, **fields) -> str:
        audit_id = uuid.uuid4().hex
        await self._append({"event": "request", "audit_id": audit_id, **fields})
        return audit_id

    async def record_decision(self, audit_id: str, *, decision: str, latency_ms: int | None) -> None:
        await self._append({"event": "decision", "audit_id": audit_id,
                            "decision": decision, "latency_ms": latency_ms})

    async def record_execution(self, audit_id: str, result: ExecutionResult) -> None:
        await self._append({"event": "execution", "audit_id": audit_id,
                            "exit_code": result.exit_code, "duration_ms": int(result.duration * 1000)})

    async def _append(self, record: dict) -> None:
        record["ts"] = datetime.now(timezone.utc).astimezone().isoformat()
        line = json.dumps(_redact(record), ensure_ascii=False)
        async with self._lock:
            async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
                await f.write(line + "\n")
```

`_redact()` 对已知敏感键（`api_key`、`password`、`token`、`Authorization`）的值替换为 `***redacted***`；命令原文本身不脱敏。

默认路径 `~/.linuxagent/audit.log`，通过 `AppConfig.audit.path` 可覆盖。禁止关闭审计（配置项没有 `enabled: false`）。

### 4.2 CommandService（`services/command_service.py`）

职责：命令执行的业务逻辑（历史记录、统计、重试策略）。

```python
class CommandService(BaseService):
    def __init__(self, executor: CommandExecutor, learner: CommandLearner): ...

    async def run(self, command: str, context: CommandContext) -> CommandResult:
        safety = self.executor.is_safe(command)
        result = await self.executor.execute(command)
        await self.learner.record(command, result)
        return CommandResult(safety=safety, execution=result)
```

### 4.3 ChatService（`services/chat_service.py`）

职责：对话历史管理，从 LangGraph `MemorySaver` 读写，替换原手写文件 I/O。

- 历史上限从 `AppConfig.ui.max_chat_history` 读取（消除魔法数字 `20`）
- 历史文件权限 `0o600`（修复原安全问题）
- 导出格式：JSON / Markdown

### 4.4 MonitoringService（`services/monitoring_service.py`）

修复原版两大 Bug：
1. `start()` / `stop()` 方法实现（原 `AlertManager` 缺失导致崩溃）
2. 监控线程在 `start()` 调用时才启动（原版从未自动启动）

```python
class MonitoringService(BaseService):
    async def start(self) -> None:
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
```

修复 `psutil` 误用（见 R-SEC 审查）：
```python
import platform, sys
info = {
    "platform": platform.system(),          # 原版错误：psutil.LINUX（布尔值）
    "python_version": sys.version,          # 原版错误：psutil.version_info（psutil版本）
}
```

### 4.5 ClusterService（`services/cluster_service.py`）

封装 `SSHManager`，统一集群命令的并发执行、结果聚合、错误隔离。

```python
class ClusterService(BaseService):
    async def run_on_all(self, command: str) -> dict[str, ExecutionResult]:
        tasks = {
            host: asyncio.create_task(self._run_on_host(host, command))
            for host in self.config.hosts
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return dict(zip(tasks.keys(), results))
```

### 4.6 瘦 Agent 协调器（`app/agent.py`）

原 4710 行 God Object 替换为 ≤300 行的协调器：

```python
class LinuxAgent:
    def __init__(
        self,
        graph: CompiledGraph,
        command_svc: CommandService,
        chat_svc: ChatService,
        monitor_svc: MonitoringService,
        cluster_svc: ClusterService,
    ): ...

    async def run(self) -> None:
        await self.monitor_svc.start()
        try:
            async for event in self.ui.input_stream():
                await self.graph.ainvoke({"messages": [HumanMessage(event)]})
        finally:
            await self.monitor_svc.stop()
```

---

## 验收标准

- [ ] `app/agent.py` 行数 ≤ 300（CI 检查）
- [ ] LangGraph 图可用 `graph.get_graph().draw_mermaid()` 可视化，流程正确
- [ ] `MonitoringService.start()` / `stop()` 单元测试通过
- [ ] 对话历史文件创建时权限为 `0o600`
- [ ] 递归重试替换为图循环：连续失败 3 次后返回错误，不崩溃
- [ ] `confirm_node` 使用 `interrupt()` 实现，图节点内无 `input()` / `prompt_toolkit` / `click.confirm` 调用（grep 验证）
- [ ] 中断后 Ctrl-C 退出再次启动可通过 `thread_id` 恢复到 confirm 点
- [ ] 无 TTY 环境下 confirm 自动返回 `non_tty_auto_deny`，图走到 `respond_refused`
- [ ] LLM 来源的相同命令第二次调用命中会话白名单，跳过 confirm；进程重启后白名单清空
- [ ] 破坏性命令（如 `rm -rf /tmp/x`）即使已在白名单仍每次 CONFIRM
- [ ] 批量 ≥2 台的集群命令强制 CONFIRM，不受 `--yes` / 白名单影响
- [ ] `~/.linuxagent/audit.log` 自动创建为 `0o600`，每次 HITL 事件追加 JSONL 记录
- [ ] `mypy src/linuxagent/services/ src/linuxagent/app/ src/linuxagent/graph/ src/linuxagent/audit.py` 零错误

---

<!-- 完成记录（完成后追加） -->
