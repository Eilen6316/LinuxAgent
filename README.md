# LinuxAgent

LinuxAgent is an LLM-driven Linux operations assistant CLI with Human-in-the-Loop safety.

The `v4` codebase is a full rewrite built on `LangGraph`, `LangChain`, and `Pydantic v2`. It replaces the frozen legacy `v3` implementation with a smaller, testable, policy-driven architecture.

## Status

- `Plan1-5` are implemented.
- `Plan6` is in progress: console UI, harness, CI, and release scaffolding are in place.
- The active package lives under `src/linuxagent/`.
- Legacy code is kept under `legacy/` for reference only.

## Highlights

- Token-level command safety classification with `SAFE` / `CONFIRM` / `BLOCK`
- Human-in-the-Loop confirmation flow backed by LangGraph `interrupt()`
- SSH cluster execution with host key verification and batch-confirm support
- LangChain-based provider abstraction for OpenAI-compatible and Anthropic models
- Tool-driven command generation with audit logging and session whitelist rules
- YAML-driven harness scenarios for HITL, dangerous commands, and cluster flows

## Requirements

- Python `3.11+`
- Linux or macOS shell environment
- Network access for live LLM calls
- A configured `config.yaml` with `api.api_key`

## Quick Start

1. Create a dev environment:

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
```

2. Edit `./config.yaml` and set:

```yaml
api:
  api_key: "your-real-key"
```

3. Validate configuration:

```bash
linuxagent check
```

4. Start the interactive CLI:

```bash
linuxagent chat
```

## Common Commands

```bash
make test
make lint
make type
make security
make harness
make build
```

## Project Layout

```text
src/linuxagent/     main v4 package
tests/unit/         unit tests
tests/integration/  optional integration tests
tests/harness/      YAML scenario harness
prompts/            runtime prompt templates
configs/            default and example config files
legacy/             frozen v3 code
```

## Safety Model

- LLM-generated commands confirm on first run.
- Destructive commands never become session-whitelisted.
- Batch cluster operations confirm when target count meets the threshold.
- Non-TTY confirmation requests auto-deny.
- All HITL decisions append to `~/.linuxagent/audit.log` with `0600` permissions.

## Build And Release

Local build and release-related steps are described in `docs/release.md`.

## Documentation

- `docs/quickstart.md`
- `docs/development.md`
- `docs/release.md`

## License

MIT
