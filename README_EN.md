# LinuxAgent

LinuxAgent is an LLM-driven Linux operations assistant CLI focused on safe command execution, Human-in-the-Loop approval, and testable orchestration.

The current codebase is the `v4` rewrite built on `LangGraph`, `LangChain`, and `Pydantic v2`.

## Why It Was Rewritten

The earlier architecture had several hard limits:

- one oversized agent object holding parsing, execution, UI, SSH, and monitoring logic
- unsafe command execution patterns and weak validation around model-generated commands
- SSH trust-policy problems
- effectively no meaningful test coverage
- limited separation between interaction flow, command policy, and infrastructure

`v4` replaces that with small modules, explicit interfaces, graph-driven control flow, and a policy-first execution model.

## Architecture Comparison

| Area | Previous design | Current `v4` design |
|---|---|---|
| Orchestration | ad-hoc control flow in a large agent class | `LangGraph` state machine with explicit nodes and edges |
| Command safety | fragile path checks and implicit flow coupling | token-level safety classification with `SAFE` / `CONFIRM` / `BLOCK` |
| HITL | mixed into application logic | `interrupt()`-based confirmation with audit trail |
| SSH | less isolated from app flow | dedicated cluster layer and service boundary |
| Configuration | less explicit and easier to bypass | fail-fast `Pydantic v2` validation |
| Intelligence | feature ideas without strong runtime wiring | learner, semantic helpers, recommendations, tool-calling integration |
| UI | tightly coupled terminal behavior | dedicated `ConsoleUI` implementing `UserInterface` |
| Testing | minimal protection | unit tests, harness scenarios, integration scaffolding, CI gates |
| Packaging | older project layout and release flow | `pyproject.toml`, wheel/sdist build path, release workflow |

## Feature Comparison

| Capability | Earlier generation | Current `v4` |
|---|---|---|
| Natural language to command | basic | provider-backed prompt flow plus tool-assisted generation |
| First-run approval for model commands | incomplete | enforced |
| Destructive command re-confirmation | incomplete | enforced |
| Batch cluster confirmation | limited | enforced at graph level |
| Audit logging | limited | append-only JSONL audit log |
| Session whitelist | limited | policy-aware and non-persistent |
| Context handling | basic history | checkpoint-aware context window with compression |
| Recommendations | concept-level | wired through learner and intelligence tools |
| Harness verification | none | YAML scenarios for basic, dangerous, cluster, and HITL flows |

## Repository Layout

```text
src/linuxagent/     active package
tests/unit/         unit suite
tests/integration/  optional integration coverage
tests/harness/      YAML scenario harness
configs/            default and example config files
prompts/            runtime prompts
docs/               user and release documentation
scripts/            bootstrap and verification scripts
```

## Installation

### Developer setup

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
```

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp configs/example.yaml config.yaml
chmod 600 config.yaml
```

## Configuration

LinuxAgent reads configuration from `config.yaml`.

Minimum required setup:

```yaml
api:
  api_key: "your-real-key"
```

Validate configuration:

```bash
linuxagent check
```

## Usage Tutorial

### Start the CLI

```bash
linuxagent chat
```

### Typical flow

1. Enter a natural-language Linux task.
2. LinuxAgent proposes a command.
3. Safety policy classifies it as `SAFE`, `CONFIRM`, or `BLOCK`.
4. If confirmation is required, the UI shows command, rule, source, and batch scope.
5. Execution results are analyzed and returned in operator-friendly text.

### Example prompts

- `show disk usage for /var`
- `check nginx status`
- `search auth logs for failed ssh logins`
- `run uptime on all hosts`

### Development commands

```bash
make test
make lint
make type
make security
make harness
make build
```

## Safety Model

- model-generated commands confirm on first run
- destructive commands never become permanently whitelisted in-session
- batch cluster operations confirm when host count meets the threshold
- non-TTY confirmation requests auto-deny
- all HITL events append to `~/.linuxagent/audit.log`

## Build And Release

Local release path:

```bash
python -m tests.harness.runner --scenarios tests/harness/scenarios
python -m build --no-isolation
./scripts/verify_wheel_install.sh
```

Tag release:

```bash
git tag v4.0.0
git push origin v4.0.0
```

## Documentation

- [Quick Start](docs/quickstart.md)
- [Development Guide](docs/development.md)
- [Release Guide](docs/release.md)

## License

MIT
