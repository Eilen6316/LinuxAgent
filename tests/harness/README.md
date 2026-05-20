# Harness

YAML-driven end-to-end scenarios for the LangGraph workflow.

Run locally:

```bash
make harness
```

Each scenario file may contain one or more YAML documents. The runner supports:

- `scenario`: human-readable name
- `provider_responses`: ordered fake LLM outputs for the scenario
  - string entries are returned as normal LLM text
  - object entries in a tool-enabled scenario can script workspace tool calls:
    `{tool_calls: [{tool: read_file, args: {path: ...}}], response: "...json..."}`
  - object entries with `{raises: ProviderError, node: ..., mode: ...}` raise a
    deterministic provider failure for a matching structured LLM call
- `inputs`: list of `{role, content}` messages (first human input drives the turn)
- `turns`: optional multi-turn replacement for `inputs`/`expected`/`resume`;
  each turn may define `input`, `expected_interrupts`, `resume`,
  `resume_sequence`, and `expected`
- `setup.session_whitelist`: commands to preload into the executor whitelist
- `setup.background_jobs`: enable a deterministic fake background-job controller
- `setup.file_patch`: `FilePatchConfig` overrides for the scenario
- `setup.sandbox`: `SandboxConfig` overrides for local runner scenarios
- `setup.files`: temporary files to create before graph execution
- `setup.symlinks`: symlinks to create before graph execution
- `setup.tool_probes`: workspace tool calls to run through the tool sandbox
- `expected_interrupts`: fields to assert on the first interrupt payload
- `resume`: payload passed to `Command(resume=...)`
- `expected`: outcome checks including `command_executed`, `exit_code`,
  `response_contains`, `audit_log_contains`, `tool_events`,
  `tool_event_sequence`, `runtime_events`, `runtime_event_sequence`,
  `background_jobs`, and `files`
