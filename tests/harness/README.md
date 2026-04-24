# Harness

YAML-driven end-to-end scenarios for the LangGraph workflow.

Run locally:

```bash
python -m tests.harness.runner --scenarios tests/harness/scenarios
```

Each scenario file may contain one or more YAML documents. The runner supports:

- `scenario`: human-readable name
- `provider_responses`: ordered fake LLM outputs for the scenario
- `inputs`: list of `{role, content}` messages (first human input drives the turn)
- `setup.session_whitelist`: commands to preload into the executor whitelist
- `expected_interrupts`: fields to assert on the first interrupt payload
- `resume`: payload passed to `Command(resume=...)`
- `expected`: outcome checks including `command_executed`, `exit_code`, `response_contains`, and `audit_log_contains`
