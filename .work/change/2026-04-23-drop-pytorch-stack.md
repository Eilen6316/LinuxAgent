# 放弃本地深度学习依赖，语义检索改走 LLM Embedding API

- **日期**：2026-04-23
- **类型**：设计变更
- **影响范围**：`plan/Plan5.md`、`plan/Plan6.md`、`design/architecture.md`、`.work/README.md`、`.gitignore`
- **决策者**：项目所有者

## 背景

初版 Plan 5 §5.3 规划使用 `sentence-transformers` 做语义相似度检索，`KnowledgeBase` 使用 `langchain-community` 的 `InMemoryVectorStore`。评估后发现：

1. **依赖体量**：`sentence-transformers` 拉入 `torch`（数百 MB）+ `transformers` + `huggingface-hub`，对一个 Linux 运维 CLI 明显过重
2. **首装体验**：`pip install linuxagent` 将触发 torch 下载，在窄带 / 容器 / CI 环境下体验差
3. **冷启动延迟**：首次加载 MiniLM 模型需额外几百毫秒到数秒
4. **`langchain-community` 冗余**：`InMemoryVectorStore` 自 `langchain-core >= 0.2.11` 起已位于 `langchain_core.vectorstores`，无需再引入 community 包
5. **运行时已强制配置 LLM**：既然 API Key 是必需项，复用同一端点的 embedding API 不会增加用户配置负担

## 新决策

### 1. 禁用的运行时依赖

`[project.dependencies]` 中**禁止**出现：

- `sentence-transformers`
- `torch` / `torchvision` / `torchaudio`
- `transformers`（Hugging Face）
- `langchain-community`
- `scikit-learn`（若仅用于 TF-IDF 或简单聚类）
- `pandas`、`numpy`（若仅用于辅助数据处理；确需数值计算再单独评估）

### 2. 语义检索替代方案

统一走 LLM Provider 的 embedding API（`OpenAIEmbeddings(model="text-embedding-3-small")` 或兼容端点）：

```python
from langchain_core.embeddings import Embeddings

class NLPEnhancer:
    def __init__(self, embeddings: Embeddings): ...
    async def find_similar_commands(self, query, candidates, top_k=5): ...
```

### 3. 调用成本与缓存

- 首选模型 `text-embedding-3-small`（OpenAI 最便宜的 embedding）
- DeepSeek 等兼容端点若无 embedding 模型，则回退到显式告知用户「未配置 embedding，此功能降级」
- 调用结果走磁盘 LRU 缓存：`~/.cache/linuxagent/embeddings/`，文件权限 `0o600`，按 query + 模型名做 key
- 离线 / 无网环境下 `NLPEnhancer` 不可用，但 Agent 主流程（命令解析、执行、安全检查）不依赖它，仅降级 UX

### 4. 测试策略

单元测试使用 `langchain_core.embeddings.FakeEmbeddings`（或手写桩）替代真实 API，**不得**在 CI 中发起真实 embedding 调用。

### 5. 向量存储

`KnowledgeBase` 使用 `langchain_core.vectorstores.InMemoryVectorStore`（随 `langchain-core` 提供，无新增依赖）。如未来需要持久化，另行评估 `chroma-core` 或 `qdrant-client` 并走 `change/`。

## 影响

- **受影响文档**：
  - `plan/Plan5.md` §5.3 / §5.5 / §新增依赖 / §验收 全面改写
  - `plan/Plan6.md` §6.5 依赖清单移除 `sentence-transformers`、`langchain-community`
  - `design/architecture.md` §框架栈「语义检索」行改为 LLM Embedding API
  - `.work/README.md` §技术栈同步更新
  - `.gitignore` 移除 `sentence-transformers / huggingface cache` 相关注释
  - 覆盖 `change/2026-04-23-adopt-langgraph-harness.md` 中"语义检索换用 sentence-transformers"的表述（按「日期更新者优先」原则）

- **受影响代码**：尚未实现

## 是否向后兼容

**否** —— 但本项目处于 v4 重写期，无存量实现依赖 sentence-transformers，无迁移成本。
