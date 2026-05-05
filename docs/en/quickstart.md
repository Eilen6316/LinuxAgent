# Quick Start

This is the shortest path from a fresh checkout to a visible, audited,
operator-approved command.

## One-Minute Path

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh
source .venv/bin/activate
```

Edit the generated `config.yaml` and set one provider.

Remote provider:

```yaml
api:
  provider: deepseek
  api_key: "your-real-key"
```

Local OpenAI-compatible provider:

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

Validate and start:

```bash
linuxagent check
linuxagent
```

Try a read-only request:

```text
check the Linux version
```

When LinuxAgent proposes a first LLM-generated command, use the confirmation
menu:

- `Yes`: run this operation once.
- `Yes, don't ask again`: allow matching commands only in this conversation and
  the same `/resume` thread.
- `No`: refuse the operation.

Direct operator commands use the `!` prefix and stream output into the current
conversation context:

```text
!uname -a
```

Use `/resume` to reopen a saved thread and `/new` to reset the current
conversation.

## Configuration Notes

LinuxAgent reads configuration from `config.yaml`. The file must be owned by
the current user and `chmod 600`; real secrets are not loaded from `.env`.

For API relays or other OpenAI-compatible endpoints:

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: gpt-4o-mini
  api_key: "your-real-key"
  token_parameter: max_tokens
```

Provider shortcuts `glm`, `qwen`, `kimi`, `minimax`, `gemini`, and `hunyuan`
use the same OpenAI-compatible path. Local OpenAI-compatible servers can use
`provider: ollama`, `vllm`, `lmstudio`, or `local` without a real API key.
Anthropic-format relays can use `provider: anthropic_compatible` after
installing the Anthropic extra; Xiaomi MiMo can use `provider: xiaomi_mimo`.

For the full matrix, see [Provider Compatibility Matrix](provider-matrix.md).

## Useful Dev Commands

```bash
make test
make lint
make type
make security
make harness
```
