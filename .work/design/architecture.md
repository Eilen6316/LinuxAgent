# 架构决策记录（ADR-001）：LinuxAgent 完全重写

**日期**：2026-04-23
**状态**：已批准
**背景**：代码审查发现原 v3 存在多处高危漏洞、God Object、零测试覆盖，维护成本超过重写成本。

---

## 核心问题诊断

| 类别 | 原始问题 | 严重度 |
|---|---|---|
| 安全 | `shell=True` + 未校验 LLM 输出 | Critical |
| 安全 | 危险命令过滤用字符串 `in`，正则形同虚设 | Critical |
| 安全 | SSH `AutoAddPolicy`，无主机密钥验证 | Critical |
| 架构 | `agent.py` 4710 行 / 86 方法的 God Object | High |
| 架构 | `config.yaml` 三大配置节被静默丢弃 | High |
| 运行时 | `AlertManager.start()` 不存在，必然崩溃 | High |
| 运行时 | 流式超时死代码，永远不会触发 | High |
| 质量 | 零单元测试，无法安全重构 | High |
| 质量 | 7 个无用依赖 | Low |

---

## 选定架构：LangGraph + 分层 + 依赖注入

引入业界主流 Agent 编排框架，用成熟的状态机 + Tool Calling 模式替换原手写 if/else 嵌套。

### 框架栈

| 层次 | 框架 | 用途 |
|---|---|---|
| Agent 编排 | **LangGraph** | 状态机、checkpointing、条件边、循环控制 |
| LLM 抽象 | **LangChain Core** | ChatModel、Messages、Tools、PromptTemplate |
| LLM Provider | langchain-openai / langchain-anthropic | OpenAI / DeepSeek / Claude |
| 配置验证 | **Pydantic v2** | fail-fast 校验、SecretStr |
| 重试 | **tenacity** | 指数退避、特定异常重试 |
| 测试 Harness | **LangGraph Studio 兼容 runner** | YAML 场景驱动端到端测试 |
| 追踪（可选） | **LangSmith** | 生产环境 Agent 调用链路追踪 |
| 语义检索 | **LLM Embedding API** | 经 `langchain-openai` 调用远端 embedding，替换原手写 TF-IDF，不引入本地模型 |

### 分层结构

```
┌─────────────────────────────────────┐
│              CLI / UI 层             │  ← src/linuxagent/cli.py + ui/
├─────────────────────────────────────┤
│       Application 层（协调器）        │  ← app/agent.py ≤300 行
├─────────────────────────────────────┤
│     LangGraph Agent 编排层           │  ← graph/
│     parse → safety → execute →       │
│     analyze → respond                │
├──────────────┬──────────────────────┤
│  核心服务层   │   Intelligence 层     │  ← services/ + intelligence/
│  CommandSvc  │   CommandLearner      │     (注册为 LangChain tools)
│  ChatSvc     │   NLPEnhancer         │
│  MonitorSvc  │   RecommendationEng   │
│  ClusterSvc  │   KnowledgeBase       │
├──────────────┴──────────────────────┤
│           基础设施层                 │  ← providers/ + executors/
│   BaseLLMProvider (LangChain包装)    │
│   CommandExecutor (安全沙箱)         │
│   SSHManager (known_hosts)          │
├─────────────────────────────────────┤
│         配置 / 日志 / 接口层          │  ← config/ + interfaces/
└─────────────────────────────────────┘
```

### 被否决的方案

**方案 A：原地修补**
否决原因：God Object 无法在不破坏功能的情况下渐进拆分；安全漏洞分散在强耦合路径上，补丁无法被测试覆盖验证。

**方案 B：微服务拆分**
否决原因：项目定位是本地 CLI 工具，微服务引入的网络复杂度不必要；单进程分层已满足需求。

**方案 C：自研 Agent 编排**
否决原因：LangGraph 已提供成熟的状态机、checkpointing、tool calling、循环控制，自研等于重造轮子且无社区生态支持。

**方案 D：LlamaIndex / AutoGen**
否决原因：LlamaIndex 偏向 RAG 场景，不适合命令执行类 Agent；AutoGen 偏多 Agent 协作，对单 Agent + 工具调用反而过度复杂。LangGraph 是单 Agent + Tool + 状态机场景的最佳匹配。

---

## 关键设计决策

### D-1：命令执行绝对禁用 `shell=True`

所有子进程调用使用列表参数 `subprocess.run(["cmd", "arg1"], ...)`。
交互式命令（`vim`、`top` 等）通过白名单精确匹配命令名（`shlex.split(cmd)[0]`），而非字符串包含。

### D-2：危险命令检测改为 token 级分析

不再使用字符串 `in` 或简单正则，改为 `shlex.split` 解析后对 token 逐个检测，再辅以正则匹配参数组合。

### D-3：LLM Provider 基于 LangChain ChatModel

`BaseLLMProvider` 封装 `langchain_core.language_models.BaseChatModel`，实现公共逻辑（重试、超时、流式、错误映射）。子类只需指定底层 ChatModel 实例（`ChatOpenAI`、`ChatAnthropic` 等）。

### D-4：Config 使用 Pydantic v2 做完整验证

所有配置节全部映射为带类型的 Pydantic 模型，启动时失败快速（fail-fast）。

### D-5：LangGraph 替代手写主循环

原 `process_user_input` 递归 + if/else 嵌套改为 LangGraph `StateGraph`：
- 节点函数替代方法，每个节点职责单一可独立测试
- 条件边替代 if/else 分支
- 循环边（带迭代上限）替代递归重试，杜绝栈溢出
- `MemorySaver` checkpointing 替代手写 JSON 文件

### D-6：SSH 强制 known_hosts 验证

默认使用 `paramiko.RejectPolicy`；可选 `WarningPolicy`（需在 config 中显式开启）。永不使用 `AutoAddPolicy`。

### D-7：Harness 驱动端到端验证

引入 YAML 场景文件 + LangGraph runner 的 harness 模式，作为 CI 必过门禁。兼容 LangSmith 追踪以便线上问题复盘。

### D-8：Intelligence 模块全部包装为 LangChain Tools

原版 `RecommendationEngine.get_recommendations()` 这类方法改为 `@tool` 装饰的函数，由 LangGraph agent 按需调用，而不是 Agent 类显式编排。

### D-9：Human-in-the-Loop 作为一等原则

Agent 的 HITL 机制不能是某个节点里的 `if/else`，必须是架构级贯穿。核心原则（完整规则见 `rule/baseline.md` R-HITL）：

1. **默认怀疑 LLM**：LLM 生成的命令默认 CONFIRM；会话级白名单是唯一降级途径，进程退出即失效
2. **批量不可降级**：≥2 台主机的集群操作强制确认，不受 `--yes` / 白名单影响
3. **破坏性永不降级**：`rm -rf` / `mkfs` / `dd` 等模式每次执行都 CONFIRM
4. **`interrupt()` 原生机制**：confirm 节点通过 `langgraph.types.interrupt()` 实现，支持中断—持久化—恢复，禁止在图节点内同步 `input()`
5. **非交互安全默认**：无 TTY / 超时时 CONFIRM 视为拒绝，禁止静默通过
6. **审计强制**：所有人工决策 JSONL 追加到 `~/.linuxagent/audit.log`（`0o600`，不轮转）

#### D-9 节点骨架（Plan 4 实现参考）

```python
# graph/nodes.py
from langgraph.types import interrupt, Command
from langchain_core.messages import AIMessage

async def confirm_node(state: AgentState) -> Command:
    audit_id = await audit.begin(state)
    # interrupt() 抛出 GraphInterrupt，MemorySaver 持久化当前状态
    # 前端（CLI / Web / Studio）通过 Command(resume={...}) 恢复
    response = interrupt({
        "type": "confirm_command",
        "command": state["pending_command"],
        "safety_level": state["safety_level"],
        "matched_rule": state.get("matched_rule"),
        "batch_hosts": state.get("batch_hosts", []),
        "command_source": state.get("command_source", "llm"),
        "audit_id": audit_id,
    })
    decision = response["decision"]             # yes | no | non_tty_auto_deny | timeout
    await audit.record_decision(audit_id, decision, response.get("latency_ms"))
    if decision == "yes":
        if state.get("command_source") == "llm" and not _is_destructive(state):
            session_whitelist.add(state["pending_command"])
        return Command(goto="execute")
    return Command(goto="respond_refused", update={
        "messages": [AIMessage(content=f"已拒绝：{decision}")],
    })
```

#### D-9 前端适配

| 前端 | 恢复方式 |
|---|---|
| CLI（默认） | `ConsoleUI` 监听 interrupt，打印预览 → `prompt_toolkit` 等待 y/n → `graph.ainvoke(Command(resume={...}))` |
| LangGraph Studio | 原生支持 interrupt UI，无需额外代码 |
| 非交互脚本 `--batch` | 检测到 interrupt 立即 `Command(resume={"decision": "non_tty_auto_deny"})`，写审计，图继续到 `respond_refused` |
| 未来 Web / API | 同一 interrupt 协议，HTTP poll / SSE 推送即可 |

---

## 目录结构

采用 PyPA 推荐的 **src-layout** + 领域导向子包 + 资源外置。详见变更记录 `change/2026-04-23-directory-layout.md`。

```
LinuxAgent/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  ← lint / type / unit / security / harness
│   │   └── release.yml             ← tag 触发，构建 wheel + sdist
│   └── ISSUE_TEMPLATE/
├── src/
│   └── linuxagent/                 ← 唯一发布包，src-layout
│       ├── __init__.py
│       ├── __main__.py             ← python -m linuxagent 入口
│       ├── cli.py                  ← argparse / click 入口，调用 app.Agent
│       ├── py.typed                ← PEP 561 类型标记
│       ├── app/                    ← 应用层（瘦协调器，≤300 行）
│       │   ├── __init__.py
│       │   └── agent.py
│       ├── graph/                  ← LangGraph 状态机
│       │   ├── __init__.py
│       │   ├── state.py            ← AgentState TypedDict
│       │   ├── nodes.py            ← 各节点函数
│       │   ├── edges.py            ← 条件边路由函数
│       │   └── agent_graph.py      ← StateGraph 组装
│       ├── tools/                  ← LangChain @tool 定义
│       │   ├── __init__.py         ← TOOL_REGISTRY
│       │   ├── system_tools.py
│       │   ├── intelligence_tools.py
│       │   └── cluster_tools.py
│       ├── providers/              ← LLM Provider
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── openai.py
│       │   ├── deepseek.py
│       │   ├── anthropic.py
│       │   └── factory.py
│       ├── services/               ← 核心业务服务
│       │   ├── __init__.py
│       │   ├── command_service.py
│       │   ├── chat_service.py
│       │   ├── monitoring_service.py
│       │   └── cluster_service.py
│       ├── executors/              ← 子进程安全沙箱
│       │   ├── __init__.py
│       │   ├── linux_executor.py
│       │   ├── safety.py           ← SafetyResult / is_safe
│       │   └── models.py           ← ExecutionResult 等
│       ├── cluster/                ← SSH 集群
│       │   ├── __init__.py
│       │   └── ssh_manager.py
│       ├── intelligence/           ← 智能模块
│       │   ├── __init__.py
│       │   ├── command_learner.py
│       │   ├── context_manager.py
│       │   ├── nlp_enhancer.py
│       │   ├── recommendation_engine.py
│       │   ├── knowledge_base.py
│       │   └── pattern_analyzer.py
│       ├── monitoring/             ← 系统监控
│       │   ├── __init__.py
│       │   ├── system_monitor.py
│       │   └── alert_manager.py
│       ├── ui/                     ← 控制台 UI
│       │   ├── __init__.py
│       │   ├── console.py
│       │   └── theme.py
│       ├── config/                 ← Pydantic 配置
│       │   ├── __init__.py
│       │   ├── models.py
│       │   └── loader.py
│       ├── interfaces/             ← ABC / Protocol
│       │   ├── __init__.py
│       │   ├── llm_provider.py
│       │   ├── executor.py
│       │   ├── ui.py
│       │   └── service.py
│       ├── container.py            ← 依赖注入容器
│       ├── audit.py                ← HITL 审计日志（JSONL，0o600）
│       └── logger.py               ← 日志初始化
├── tests/
│   ├── conftest.py                 ← 全局 fixtures
│   ├── unit/                       ← mirror src/linuxagent 结构
│   │   ├── test_config.py
│   │   ├── test_safety.py
│   │   ├── services/
│   │   ├── graph/
│   │   └── ...
│   ├── integration/                ← 需 --integration 标志
│   │   ├── test_agent_graph.py
│   │   ├── test_ssh.py
│   │   └── test_command_exec.py
│   └── harness/                    ← 端到端场景驱动
│       ├── README.md
│       ├── runner.py
│       └── scenarios/
│           ├── basic_commands.yaml
│           ├── dangerous_commands.yaml
│           └── cluster_ops.yaml
├── prompts/                        ← Prompt 模板（非 Python）
│   ├── system.md
│   ├── command_generation.md
│   └── analysis.md
├── configs/                        ← 配置样例
│   ├── default.yaml
│   └── example.yaml
├── docs/
│   ├── getting-started.md
│   ├── architecture.md             ← 面向用户的简化版
│   ├── configuration.md
│   └── api-reference.md
├── scripts/
│   ├── bootstrap.sh                ← 开发环境初始化
│   └── release.sh
├── legacy/                         ← v3 旧代码冷藏区，v4.0.0 发布时删除
│   ├── README.md                   ← 明确「不要修改」
│   ├── src_v3/                     ← 原 src/
│   ├── linuxagent.py               ← 原入口脚本
│   ├── setup.py
│   └── pyinstaller.spec
├── config.yaml                     ← 用户本地配置（含密钥，gitignore，chmod 600）
├── .gitignore
├── .pre-commit-config.yaml         ← ruff / mypy / bandit hooks
├── CHANGELOG.md                    ← Keep a Changelog 格式
├── LICENSE
├── Makefile                        ← make test / lint / harness / build
├── pyproject.toml                  ← PEP 517/621 单一真源
└── README.md
```

### 关键约定

1. **包名即发布名**：唯一入口 `linuxagent`，无子包对外暴露
2. **`src/` 下只有一个包**：防止扁平包命名冲突（v3 就是因为 `src/xxx` 各自是顶层包导致混乱）
3. **测试镜像源码结构**：`tests/unit/services/test_command_service.py` ↔ `src/linuxagent/services/command_service.py`
4. **资源与代码分离**：prompts / configs / scenarios 均不进 `src/`，便于独立迭代和非代码贡献
5. **legacy/ 只进不出**：v3 整体搬进来冷藏，不修不补，到 v4.0.0 发版时整块删除
6. **配置单文件**：密钥与非密钥全部在 `config.yaml` 中，不用 `.env`（见 `change/2026-04-23-config-yaml-only.md`）。用户本地 `./config.yaml` gitignore + chmod 600；`configs/default.yaml` 和 `configs/example.yaml` 作为模板入库
