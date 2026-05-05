# Provider Compatibility Matrix

LinuxAgent uses LangChain provider wrappers. Most non-Anthropic providers use
the OpenAI-compatible wire format through `langchain-openai`; Anthropic-format
providers require the optional `anthropic` extra.

This matrix documents the intended configuration path. A row marked
`compatible path` means the provider should work through the listed protocol,
but maintainers still want real endpoint reports before calling it fully
verified.

| Provider | Protocol | Typical `base_url` | Token parameter | API key | Status |
|---|---|---|---|---|---|
| `deepseek` | OpenAI-compatible | `https://api.deepseek.com/v1` | `max_completion_tokens` | Required | default path |
| `openai` | OpenAI | `https://api.openai.com/v1` | `max_completion_tokens` | Required | supported |
| `openai_compatible` | OpenAI-compatible relay | relay `/v1` URL | often `max_tokens` | Required | supported |
| `local` | OpenAI-compatible local | `http://127.0.0.1:8000/v1` | `max_tokens` | Optional | compatible path |
| `ollama` | OpenAI-compatible local | `http://127.0.0.1:11434/v1` | `max_tokens` | Optional | compatible path |
| `vllm` | OpenAI-compatible local | `http://127.0.0.1:8000/v1` | `max_tokens` | Optional | compatible path |
| `lmstudio` | OpenAI-compatible local | `http://127.0.0.1:1234/v1` | `max_tokens` | Optional | compatible path |
| `qwen` | OpenAI-compatible | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `max_tokens` | Required | compatible path |
| `kimi` | OpenAI-compatible | `https://api.moonshot.ai/v1` | `max_tokens` | Required | compatible path |
| `glm` | OpenAI-compatible | `https://open.bigmodel.cn/api/paas/v4` | `max_tokens` | Required | compatible path |
| `minimax` | OpenAI-compatible | `https://api.minimax.io/v1` | `max_tokens` | Required | compatible path |
| `gemini` | OpenAI-compatible | `https://generativelanguage.googleapis.com/v1beta/openai/` | `max_tokens` | Required | compatible path |
| `hunyuan` | OpenAI-compatible | `https://api.hunyuan.cloud.tencent.com/v1` | `max_tokens` | Required | compatible path |
| `anthropic` | Anthropic | provider default | n/a | Required | optional extra |
| `anthropic_compatible` | Anthropic-compatible relay | relay URL | n/a | Required | optional extra |
| `xiaomi_mimo` | Anthropic-compatible relay | relay URL | n/a | Required | optional extra |

## Local Models

Local providers are shortcuts for OpenAI-compatible HTTP servers. They do not
require a real API key; LinuxAgent passes a placeholder to satisfy client
construction.

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

## API Relays

When using a relay, prefer the generic path first:

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: relay-model
  api_key: "sk-..."
  token_parameter: max_tokens
```

If requests fail with an unknown parameter error, change
`api.token_parameter` between `max_tokens` and `max_completion_tokens`.

## Compatibility Reports

When reporting a provider as working or broken, include:

- provider name and endpoint type
- model name
- `token_parameter`
- whether streaming worked
- whether command planning returned valid JSON
- whether tool calls were used
- sanitized error output if it failed
