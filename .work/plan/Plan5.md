# Plan 5 · Intelligence 模块重写

**目标**：重写 `src/intelligence/` 下的六个模块，修复性能问题，集成为 LangGraph 工具节点，语义相似度改走 LLM Embedding API（见 `change/2026-04-23-drop-pytorch-stack.md`）替换原手写 TF-IDF。

**前置条件**：Plan 3（LangChain tools 框架）完成  
**交付物**：`src/linuxagent/intelligence/` + `src/linuxagent/tools/intelligence_tools.py`

---

## Scope

### 5.1 CommandLearner 重写（`intelligence/command_learner.py`）

**修复原版 O(n) 问题**：原版每次 `record_command_usage` 全量扫描历史两次（最大 10000 条）。

重写方案：维护 `dict[str, CommandStats]` 在线更新，O(1) 摊销：

```python
@dataclass
class CommandStats:
    count: int = 0
    success_count: int = 0
    total_duration: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.count if self.count else 0.0

    @property
    def avg_duration(self) -> float:
        return self.total_duration / self.count if self.count else 0.0

class CommandLearner:
    _stats: dict[str, CommandStats]  # key = 归一化命令名

    def record(self, command: str, result: ExecutionResult) -> None:
        key = self._normalize(command)
        stats = self._stats.setdefault(key, CommandStats())
        stats.count += 1
        if result.exit_code == 0:
            stats.success_count += 1
        stats.total_duration += result.duration
```

持久化：定期（或关闭时）序列化为 `~/.linuxagent_learner.json`，文件权限 `0o600`。

### 5.2 ContextManager 重写（`intelligence/context_manager.py`）

基于 LangGraph `MemorySaver` 实现上下文窗口管理，替换原手写滑动窗口。

- 上下文条数上限从 `AppConfig.intelligence.context_window` 读取
- 支持上下文压缩（LangChain `ConversationSummaryBufferMemory` 思路）

### 5.3 NLPEnhancer 重写（`intelligence/nlp_enhancer.py`）

使用 LLM Provider 的 embedding API 做语义相似度检索，替换原 TF-IDF 手写实现。**不引入本地模型依赖**（sentence-transformers / torch / transformers 一律禁用，见 `change/2026-04-23-drop-pytorch-stack.md`）。

```python
from langchain_core.embeddings import Embeddings

class NLPEnhancer:
    def __init__(self, embeddings: Embeddings):
        self._embeddings = embeddings

    async def find_similar_commands(
        self, query: str, candidates: list[str], top_k: int = 5
    ) -> list[tuple[str, float]]:
        query_emb = await self._embeddings.aembed_query(query)
        cand_embs = await self._embeddings.aembed_documents(candidates)
        scored = [
            (cand, _cosine(query_emb, emb))
            for cand, emb in zip(candidates, cand_embs)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
```

`Embeddings` 实例通过 DI 容器注入：默认 `OpenAIEmbeddings(model="text-embedding-3-small")`（低成本、兼容 DeepSeek/OpenAI 端点）。调用结果走**磁盘 LRU 缓存**（`~/.cache/linuxagent/embeddings/`，权限 `0o600`）以避免重复调用。单元测试用 `FakeEmbeddings` 替代远端调用。

### 5.4 RecommendationEngine 重写（`intelligence/recommendation_engine.py`）

结合 `CommandLearner` 统计数据 + `NLPEnhancer` 语义相似度，生成推荐：

```python
@tool
async def get_command_recommendations(context: str) -> list[str]:
    """Suggest relevant commands based on context and usage history."""
    ...
```

注册为 LangChain tool，由 LangGraph `parse_intent` 节点调用。

### 5.5 KnowledgeBase 重写（`intelligence/knowledge_base.py`）

使用 LangChain `InMemoryVectorStore`（或可选 `Chroma` 持久化）替换原手写字典索引：

```python
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings

class KnowledgeBase:
    def __init__(self, embeddings: Embeddings):
        self._store = InMemoryVectorStore(embeddings)

    async def search(self, query: str, k: int = 5) -> list[Document]:
        return await self._store.asimilarity_search(query, k=k)
```

### 5.6 PatternAnalyzer 重写（`intelligence/pattern_analyzer.py`）

原版无明显 Bug，主要清理：
- 移除重复逻辑
- 结果包装为 `dataclass`
- 注册为 LangChain tool

### 5.7 工具注册汇总

所有 Intelligence 能力注册到一个 `ToolRegistry`：

```python
# intelligence/tools.py
INTELLIGENCE_TOOLS = [
    get_command_recommendations,
    search_knowledge_base,
    analyze_command_pattern,
    get_similar_commands,
]
```

LangGraph agent 通过 `graph.bind_tools(INTELLIGENCE_TOOLS)` 挂载。

---

## 新增依赖

**本轮不新增运行时依赖**。
- `InMemoryVectorStore` 已随 `langchain-core>=0.3` 提供（`langchain_core.vectorstores`），**不再需要 `langchain-community`**（见 Plan 3 §3.1 禁用约定）
- Embedding 能力复用 Plan 3 已引入的 `langchain-openai`
- 如需磁盘缓存，使用 Python 标准库（`pathlib` + JSON）或后续单独评估 `diskcache`

**禁用依赖**：`sentence-transformers`、`torch`、`transformers`、`scikit-learn`、`pandas`、`numpy`（若仅用于 TF-IDF）—— 见 `change/2026-04-23-drop-pytorch-stack.md`。

---

## 验收标准

- [ ] `CommandLearner.record()` 基准测试：10000 次记录 < 100ms（原版约 10s）
- [ ] `NLPEnhancer.find_similar_commands` 单元测试用 `FakeEmbeddings`（不发起真实 API 调用）验证语义相关命令排名高于无关命令
- [ ] 所有 Intelligence 功能注册为 LangChain tool 并在 LangGraph 图中可调用
- [ ] 持久化文件权限均为 `0o600`
- [ ] `mypy src/linuxagent/intelligence/` 零错误

---

<!-- 完成记录（完成后追加） -->
