# Development

## Architecture

The active codebase is the `v4` rewrite under `src/linuxagent/`.

Core layers:

- `config/`: validated application configuration
- `providers/`: LangChain-backed LLM providers
- `executors/`: safe local command execution
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

## Repository Note

The old `v3` source has been removed. All active work belongs in `src/linuxagent/`.
