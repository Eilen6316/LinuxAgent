# Migration Guide: v3 to v4.0.0

LinuxAgent v4.0.0 is a full rewrite. It is not a drop-in upgrade from the
earlier prototype.

## What Changed

| Area | v3 | v4.0.0 |
|---|---|---|
| Package layout | Flat prototype code | `src/linuxagent/` src-layout package |
| Configuration | Ad hoc files and environment patterns | `config.yaml`, Pydantic v2 validation, `chmod 600` required |
| Command safety | Substring checks | Capability-based policy engine using token facts |
| LLM output | Raw command strings | Validated JSON `CommandPlan` |
| Orchestration | Single large agent class | LangGraph state machine |
| SSH trust | Unsafe host-key behavior in old code | `RejectPolicy` plus system `known_hosts` by default |
| Audit | Optional or incomplete | Hash-chained JSONL audit log, always enabled |
| Tests | No meaningful unit coverage | Unit, integration, harness, type, lint, security, build gates |

## Required Migration Steps

1. Create a fresh virtual environment with Python 3.11 or 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Replace old configuration with `config.yaml`.

```bash
cp configs/example.yaml config.yaml
chmod 600 config.yaml
```

3. Move API credentials into `config.yaml`.

```yaml
api:
  provider: deepseek
  api_key: "replace-me"
```

For API relays or other OpenAI-compatible endpoints:

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: gpt-4o-mini
  api_key: "replace-me"
  token_parameter: max_tokens
```

Provider shortcuts `glm`, `kimi`, `minimax`, and `gemini` use the same
OpenAI-compatible path. Anthropic-format relays can use
`provider: anthropic_compatible` after installing the Anthropic extra.

Do not use `.env` for secrets. v4 only allows environment variables to point to
configuration paths, not to carry secret values.

4. Register SSH hosts before cluster use.

```bash
ssh-keyscan -H your-host.example.com >> ~/.ssh/known_hosts
```

v4 rejects unknown host keys by default.

5. Validate locally.

```bash
linuxagent check
linuxagent
```

## Behavior Changes Operators Will Notice

- First-time LLM-generated commands require confirmation.
- Destructive commands require confirmation every time and are never
  whitelisted.
- Non-interactive callers auto-deny command confirmations.
- Cluster operations across two or more hosts require explicit batch
  confirmation.
- Commands that contain shell chaining, redirects, substitutions, or variable
  expansion may be blocked in SSH cluster mode.
- Command output sent to LLM analysis paths is guarded and redacted.

## Replacing Old Customizations

| Old customization | v4 replacement |
|---|---|
| Hard-coded prompt edits | Edit files under `prompts/` |
| Direct command allow/block edits | Use `configs/policy.default.yaml` as a template and configure `policy.path` |
| Custom scripted workflow | Add a YAML runbook under `runbooks/` and cover it with harness scenarios |
| Local history tweaks | Use the built-in audit and telemetry files |

## Rollback Guidance

Keep v3 and v4 deployments separate. Do not share config files, history files,
or audit files between versions. If you need to keep v3 for a legacy workflow,
run it from a separate checkout and do not mix imports with the v4 package.
