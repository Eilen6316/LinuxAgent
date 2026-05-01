# Quick Start

## 1. Bootstrap

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
```

## 2. Configure

LinuxAgent reads configuration from `config.yaml`.

The normal local workflow is:

```bash
cp configs/example.yaml config.yaml
chmod 600 config.yaml
```

Set at least:

```yaml
api:
  api_key: "your-real-key"
```

For API relays or other OpenAI-compatible endpoints:

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: gpt-4o-mini
  api_key: "your-real-key"
  token_parameter: max_tokens
```

Provider shortcuts `glm`, `kimi`, `minimax`, and `gemini` use the same
OpenAI-compatible path. Anthropic-format relays can use
`provider: anthropic_compatible` after installing the Anthropic extra.

## 3. Validate

```bash
linuxagent check
```

## 4. Start The CLI

```bash
linuxagent
```

## 5. Useful Dev Commands

```bash
make test
make lint
make type
make security
make harness
```
