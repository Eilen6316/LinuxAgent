# 采用 LangChain / LangGraph 框架与 Harness 模式

- **日期**：2026-04-23
- **类型**：设计变更
- **影响范围**：`design/architecture.md`、`plan/Plan1.md`–`plan/Plan6.md`
- **决策者**：项目所有者

## 背景

初版重写方案（见 Git 历史中本文件创建前的 architecture.md 版本）只规划了「分层 + 依赖注入」的纯自研架构，所有 Agent 编排逻辑（意图解析、安全检查、工具调度、循环控制）都要手写。

评估后认为自研 Agent 编排存在以下风险：
- 状态机逻辑容易再次演变成新的 God Object（重蹈 v3 覆辙）
- 缺少 checkpointing / 追踪能力，线上问题难以复盘
- 无法复用社区 Tool Calling 生态
- Prompt 管理、消息结构、流式处理全部要重造轮子

## 新决策

1. **引入 LangGraph** 作为 Agent 状态机编排核心（见 `design/architecture.md` §选定架构）
2. **引入 LangChain Core** 作为 LLM / Messages / Tools 抽象，替代自研 Provider 接口
3. **Intelligence 模块全部包装为 `@tool`**，由 LangGraph 按需调用（见 Plan 5 §5.7）
4. **引入 YAML 场景驱动的 Harness**（Plan 6 §6.3），作为 CI 必过门禁
5. **预留 LangSmith 追踪钩子**（Plan 1 §1.5），生产环境可选启用
6. **语义检索换用 sentence-transformers**（Plan 5 §5.3），替代手写 TF-IDF

## 影响

- **受影响文档**：
  - `design/architecture.md` 整体重写为 LangGraph 主导架构，新增 D-5 / D-7 / D-8 决策
  - `plan/Plan1.md` §1.6 / §1.7 新增框架依赖与 pyproject.toml 要求
  - `plan/Plan3.md` 整体改为「LLM Provider + LangChain 集成」
  - `plan/Plan4.md` 整体改为「LangGraph Agent 编排 + 核心服务层」
  - `plan/Plan5.md` 新增 Intelligence 模块的 Tool 化改造
  - `plan/Plan6.md` §6.3 新增 Harness 子系统

- **受影响代码**：尚未实现（纯新写项目）

- **新增依赖**：`langchain-core`、`langchain-openai`、`langgraph`、`tenacity`、`sentence-transformers`

## 是否向后兼容

**否** —— 这是一次完全重写，v4.0.0 作为 Breaking Change 发布。旧 `src/agent.py` 所有自定义类对外 API 均被移除。配置文件（`config.yaml`）结构保留兼容，新增字段走默认值。
