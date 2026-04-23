# Plan 3 · LLM Provider 层 + LangChain 集成

**目标**：基于 LangChain 统一 LLM 接口，支持 OpenAI / DeepSeek / Anthropic（Claude），实现流式、重试、超时均可测试。引入 LangGraph 为后续 Agent 编排打基础。

**前置条件**：Plan 1 完成  
**交付物**：`src/linuxagent/providers/` + `src/linuxagent/tools/` + `src/linuxagent/graph/state.py`

---

## Scope

### 3.1 框架选型

| 框架 | 用途 |
|---|---|
| `langchain-core` | ChatModel 抽象、Messages、PromptTemplate、OutputParser |
| `langchain-openai` | OpenAI / DeepSeek（兼容 OpenAI API）Provider |
| `langchain-anthropic` | Anthropic Claude Provider（可选后备） |
| `langgraph` | Agent 状态机编排（Plan 4 使用，本轮定义 Graph schema） |

**不引入** `langchain-community`（避免隐式依赖爆炸）。

### 3.2 Provider 层架构

```
providers/
├── base.py           ← BaseLLMProvider（封装 LangChain ChatModel）
├── openai.py         ← OpenAIProvider：gpt-4o / gpt-4o-mini
├── deepseek.py       ← DeepSeekProvider：复用 OpenAI 兼容端点
├── anthropic.py      ← AnthropicProvider：claude-opus-4-7（可选）
└── factory.py        ← provider_factory(config) → BaseLLMProvider
```

**`BaseLLMProvider`** 封装公共逻辑，子类只需提供端点和模型映射：

```python
class BaseLLMProvider:
    def __init__(self, config: APIConfig, chat_model: BaseChatModel): ...

    async def complete(self, messages: list[BaseMessage], **kwargs) -> str:
        # 统一重试（tenacity）+ 超时 + 错误映射
        ...

    async def stream(self, messages: list[BaseMessage]) -> AsyncIterator[str]:
        # LangChain astream()，修复原版超时死代码
        async for chunk in self._model.astream(messages):
            yield chunk.content
```

### 3.3 流式超时修复

原版 `deepseek.py` 的 timeout 死代码（`last_chunk_time` 每次循环重置）在本轮彻底替换：

```python
async def stream(self, messages):
    async with asyncio.timeout(self.config.stream_timeout):
        async for chunk in self._model.astream(messages):
            yield chunk.content
            # asyncio.timeout 在整个流的层面处理超时，无需手动计时
```

### 3.4 LangChain Tools 定义

将命令执行、系统监控等操作包装为 LangChain `@tool`，供 LangGraph Agent 调用：

```python
# tools/system_tools.py
@tool
async def execute_command(command: str) -> str:
    """Execute a Linux shell command safely."""
    ...

@tool
async def get_system_info() -> dict:
    """Get current system resource usage."""
    ...

@tool
async def search_logs(pattern: str, log_file: str) -> list[str]:
    """Search system logs for a pattern."""
    ...
```

### 3.5 LangGraph Graph Schema（骨架）

定义 Agent 状态机结构，Plan 4 填充节点实现：

```python
# graph/state.py
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    pending_command: str | None
    execution_result: ExecutionResult | None
    safety_level: SafetyLevel | None
    user_confirmed: bool

# 节点（Plan 4 实现）：
# parse_intent → safety_check → [confirm_user | execute] → analyze_result → respond
```

### 3.6 Prompt 管理

所有运行时 prompt 从仓库根 `prompts/` 目录加载，使用 LangChain `ChatPromptTemplate`。`.work/prompt/` 不参与运行时加载：

```python
from langchain_core.prompts import ChatPromptTemplate

COMMAND_GEN_PROMPT = ChatPromptTemplate.from_messages([
    ("system", Path("prompts/system.md").read_text()),
    ("human", "{user_input}"),
    MessagesPlaceholder("chat_history"),
])
```

禁止 prompt 硬编码在 Python 文件中。

### 3.7 重试策略

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
)
async def _call_with_retry(self, ...): ...
```

---

## 新增依赖

```
langchain-core>=0.3,<0.4
langchain-openai>=0.2,<0.3
langchain-anthropic>=0.3,<0.4   # 可选
langgraph>=0.2,<0.3
tenacity>=8.0,<10.0
```

---

## 验收标准

- [ ] `OpenAIProvider` 和 `DeepSeekProvider` 共享 `BaseLLMProvider`，无重复代码
- [ ] 流式调用：断开连接时 `asyncio.timeout` 正确抛出 `TimeoutError`
- [ ] Provider 单元测试使用 `langchain_core.fake.FakeChatModel` mock，无真实 API 调用
- [ ] `provider_factory` 根据 `config.api.provider` 返回正确实例
- [ ] LangGraph `AgentState` schema 定义完整，`mypy` 通过
- [ ] `mypy src/linuxagent/providers/ src/linuxagent/graph/ src/linuxagent/tools/` 零错误

---

<!-- 完成记录（完成后追加） -->
