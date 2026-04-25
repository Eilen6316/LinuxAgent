# Development

## Architecture

The active codebase is the `v4` rewrite under `src/linuxagent/`.

Core layers:

- `config/`: validated application configuration
- `providers/`: LangChain-backed LLM providers
- `executors/`: safe local command execution
- `policy/`: capability-based command policy engine
- `cluster/`: SSH execution and host policy
- `graph/`: LangGraph orchestration
- `services/`: application services
- `intelligence/`: learner, semantic helpers, recommendations
- `ui/`: terminal UI

## Test Matrix

- `tests/unit/`: default CI test suite
- `tests/integration/`: optional integration coverage
- `tests/harness/`: YAML scenarios for graph and HITL behavior

Run locally:

```bash
pytest tests/unit/ --cov=linuxagent --cov-fail-under=80
python -m tests.harness.runner --scenarios tests/harness/scenarios
```

## Security Red Lines

These are enforced both locally and in CI:

- no `shell=True`
- no `AutoAddPolicy`
- no bare `except:`
- no `input()` calls inside `src/linuxagent/graph/`

## Policy Rules

Command safety is evaluated by `src/linuxagent/policy/` and exposed through
the compatibility API in `src/linuxagent/executors/safety.py`.

Each decision includes:

- `level`: `SAFE`, `CONFIRM`, or `BLOCK`
- `risk_score`: 0-100
- `capabilities`: e.g. `filesystem.delete`, `service.mutate`, `privilege.sudo`
- `matched_rules`: legacy-compatible rule names used by audit and HITL

`configs/policy.default.yaml` documents the default YAML shape:

```yaml
rules:
  - id: service.mutate
    legacy_rule: DESTRUCTIVE
    level: CONFIRM
    risk_score: 70
    capabilities: [service.mutate]
    reason: service state mutation
    match:
      command: [systemctl, service]
      subcommand_any: [stop, restart, reload, disable]
```

Policy YAML is validated fail-fast with Pydantic. Runtime currently uses the
built-in rules to avoid file I/O in the hot path; user override wiring belongs
to the next policy configuration pass.

## Repository Note

The old `v3` source has been removed. All active work belongs in `src/linuxagent/`.
