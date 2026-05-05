# Provider 兼容矩阵

LinuxAgent 通过 LangChain provider wrapper 调用模型。多数 provider 走
OpenAI-compatible 协议；Anthropic 格式 provider 需要安装 `anthropic` extra。

| Provider | 协议 | 常见 `base_url` | Token 参数 | API Key | 状态 |
|---|---|---|---|---|---|
| `deepseek` | OpenAI-compatible | `https://api.deepseek.com/v1` | `max_completion_tokens` | 需要 | 默认路径 |
| `openai` | OpenAI | `https://api.openai.com/v1` | `max_completion_tokens` | 需要 | 支持 |
| `openai_compatible` | OpenAI-compatible 中转 | 中转站 `/v1` 地址 | 常见为 `max_tokens` | 需要 | 支持 |
| `local` | 本地 OpenAI-compatible | `http://127.0.0.1:8000/v1` | `max_tokens` | 可空 | 兼容路径 |
| `ollama` | 本地 OpenAI-compatible | `http://127.0.0.1:11434/v1` | `max_tokens` | 可空 | 兼容路径 |
| `vllm` | 本地 OpenAI-compatible | `http://127.0.0.1:8000/v1` | `max_tokens` | 可空 | 兼容路径 |
| `lmstudio` | 本地 OpenAI-compatible | `http://127.0.0.1:1234/v1` | `max_tokens` | 可空 | 兼容路径 |
| `qwen` | OpenAI-compatible | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `max_tokens` | 需要 | 兼容路径 |
| `kimi` | OpenAI-compatible | `https://api.moonshot.ai/v1` | `max_tokens` | 需要 | 兼容路径 |
| `glm` | OpenAI-compatible | `https://open.bigmodel.cn/api/paas/v4` | `max_tokens` | 需要 | 兼容路径 |
| `minimax` | OpenAI-compatible | `https://api.minimax.io/v1` | `max_tokens` | 需要 | 兼容路径 |
| `gemini` | OpenAI-compatible | `https://generativelanguage.googleapis.com/v1beta/openai/` | `max_tokens` | 需要 | 兼容路径 |
| `hunyuan` | OpenAI-compatible | `https://api.hunyuan.cloud.tencent.com/v1` | `max_tokens` | 需要 | 兼容路径 |
| `anthropic` | Anthropic | provider 默认地址 | n/a | 需要 | optional extra |
| `anthropic_compatible` | Anthropic-compatible 中转 | 中转站地址 | n/a | 需要 | optional extra |
| `xiaomi_mimo` | Anthropic-compatible 中转 | 中转站地址 | n/a | 需要 | optional extra |

## 本地模型示例

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

## 反馈兼容性时请提供

- provider 名称和 endpoint 类型
- model 名称
- `token_parameter`
- streaming 是否正常
- planner 是否稳定返回合法 JSON
- 是否使用 tool calling
- 失败时的脱敏错误输出
