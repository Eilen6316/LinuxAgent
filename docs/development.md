# Development

## Architecture

The active codebase is the `v4` rewrite under `src/linuxagent/`.

Core layers:

- `config/`: validated application configuration
- `providers/`: LangChain-backed LLM providers
- `executors/`: safe local command execution
- `policy/`: capability-based command policy engine
- `plans/`: strict JSON CommandPlan models and parsing
- `runbooks/`: YAML runbook models, loading, matching, and policy validation
- `cluster/`: SSH execution and host policy
- `graph/`: LangGraph orchestration
- `services/`: application services
- `telemetry.py`: local JSONL spans and trace correlation
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

## SSH Remote Execution

Local commands run through argv-based subprocess execution. Remote SSH is
stricter because Paramiko `exec_command()` talks to the remote user's shell.
`src/linuxagent/cluster/remote_command.py` therefore rejects shell syntax
before SSH fan-out: command sequencing, pipes, redirects, command
substitution, variable expansion, and related metacharacters are not allowed
on the cluster path.

The graph applies this check after host selection and returns `BLOCK` before
HITL. `SSHManager` repeats the same validation before connecting so direct
service calls cannot bypass the boundary.

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

## CommandPlan And Runbooks

The graph no longer accepts a raw shell string from the LLM. Provider output is
parsed as strict JSON `CommandPlan`; invalid JSON or schema errors are treated
as `BLOCK` and no command is executed.

Built-in runbooks live under `runbooks/`. Each runbook is YAML, has at least
three scenario phrases, and every step is policy-evaluated by
`RunbookEngine.evaluate_steps()` before it is considered usable.

## Observability And Audit

Every graph run receives a `trace_id` that is attached to HITL audit records
and local telemetry spans. The default telemetry backend writes JSONL to
`~/.linuxagent/telemetry.jsonl`; it does not require an external OTel service.

Audit records are hash-chained with `prev_hash` and `hash`. Use
`linuxagent audit verify` to validate the current audit log and locate the
first tampered line.

## Repository Note

The old `v3` source has been removed. All active work belongs in `src/linuxagent/`.
