# 本地部署模型 Provider 快捷入口

- **日期**：2026-05-02
- **类型**：偏离计划
- **影响范围**：`.work/plan/Plan8.md`；`src/linuxagent/config/`；`src/linuxagent/providers/`；`configs/`；`README.md`；`docs/`
- **决策者**：用户请求 + Codex

## 背景

Plan 8 的非 Scope 写明“不继续扩大模型 provider 抽象”，但用户明确要求新增支持本地部署的模型接口。当前代码已经可以通过 `openai_compatible` 指向本地 OpenAI-compatible 服务，但没有一等配置入口，并且 CLI 启动会强制要求真实 `api.api_key`，不适合 Ollama、vLLM、LM Studio 等本地部署端点。

## 新决策

新增本地部署模型 provider 快捷入口，仍复用现有 LangChain `ChatOpenAI` 与 OpenAI-compatible wire format，不引入新的 SDK 或本地深度学习依赖。新增入口仅改变配置可读性、默认本地端点和 API key 校验行为，不改变 LLM 调用抽象。

## 影响

- **受影响文档**：
  - `.work/plan/Plan8.md` §非 Scope
  - `configs/default.yaml`
  - `configs/example.yaml`
  - `README.md`
  - `docs/en/README.md`
  - `docs/zh/README.md`
- **受影响代码**：
  - `src/linuxagent/config/models.py`
  - `src/linuxagent/providers/factory.py`
  - `src/linuxagent/providers/openai.py`
  - `tests/unit/test_config.py`
  - `tests/unit/providers/test_factory.py`

## 是否向后兼容

是。既有 `openai_compatible` 配置继续可用；新增本地 provider 只是快捷入口。本地 provider 可不填真实 API key，远端 provider 仍保持启动前强制校验 `api.api_key`。
