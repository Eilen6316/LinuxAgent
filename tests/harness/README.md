# Harness

YAML-driven end-to-end scenarios for the LangGraph workflow.

Run locally:

```bash
make harness
```

Each scenario file may contain one or more YAML documents. The runner supports:

- `scenario`: human-readable name
- `provider_responses`: ordered fake LLM outputs for the scenario
- `inputs`: list of `{role, content}` messages (first human input drives the turn)
- `setup.session_whitelist`: commands to preload into the executor whitelist
- `setup.file_patch`: `FilePatchConfig` overrides for the scenario
- `setup.sandbox`: `SandboxConfig` overrides for local runner scenarios
- `setup.files`: temporary files to create before graph execution
- `setup.tool_probes`: workspace tool calls to run through the tool sandbox
- `expected_interrupts`: fields to assert on the first interrupt payload
- `resume`: payload passed to `Command(resume=...)`
- `expected`: outcome checks including `command_executed`, `exit_code`,
  `response_contains`, `audit_log_contains`, `tool_events`, and `files`
