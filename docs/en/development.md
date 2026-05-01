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
- `graph/`: LangGraph orchestration split into intent parsing, safety checks, routing, and node factories
- `services/`: application services
- `telemetry.py`: local JSONL spans and trace correlation
- `intelligence/`: learner, semantic helpers, recommendations
- `ui/`: terminal UI

## Test Matrix

- `tests/unit/`: default CI test suite
- `tests/integration/`: optional graph/runtime/SSH integration coverage, gated by `--integration`
- `tests/harness/`: YAML scenarios for graph and HITL behavior

Run locally:

```bash
pytest tests/unit/ --cov=linuxagent --cov-fail-under=80
make sandbox
make integration
make optional-anthropic
make harness
make verify-build
```

`make integration` is intentionally optional and runs only tests marked
`integration` with the explicit `--integration` flag. Keep external-resource
coverage behind that gate so the default unit suite stays deterministic.

`make optional-anthropic` is also optional. Run `pip install -e '.[anthropic,dev]'`
first when validating Claude provider compatibility.

`make build` expects the dev build backend to be importable in the active
Python environment. Run `make install` first, or activate the project virtualenv
before building.

`make verify-build` installs the wheel in an isolated virtualenv with runtime
dependencies. It uses PyPI by default; set `LINUXAGENT_PIP_INDEX_URL` to test
against a private mirror.

## Security Red Lines

These are enforced both locally and in CI:

- no `shell=True`
- no `AutoAddPolicy`
- no bare `except:`
- no `input()` calls inside `src/linuxagent/graph/`
- no direct subprocess creation outside `src/linuxagent/sandbox/`
- no unwrapped LangChain tools exposed to the LLM

`make security` runs `scripts/check_code_rules.py`,
`scripts/check_sandbox_rules.py`, grep red-lines, and Bandit.

## Sandbox Release Checklist

Before a release or security-sensitive merge, review:

- sandbox bypass: local execution still reaches commands only through
  `SandboxRunner`.
- tool completeness: every LLM-facing tool has `ToolSandboxSpec` metadata,
  timeout/output budgets, and redacted output.
- audit completeness: command, file patch, local sandbox, and SSH remote
  metadata are recorded where applicable.
- fallback behavior: disabled/no-op paths report `enforced=false`; unavailable
  safe profiles fail closed.
- packaging: `make verify-build` confirms config, policy, prompts, runbooks,
  and sandbox config sections are present in the wheel.

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

Policy YAML is validated fail-fast with Pydantic and can be enabled at runtime:

```yaml
policy:
  path: ~/.config/linuxagent/policy.yaml
  include_builtin: true
```

With `include_builtin: true`, user rule IDs replace matching built-in IDs and
new IDs are appended. Set `include_builtin: false` only when intentionally
replacing the full policy set. Invalid configured policy YAML fails before the
runtime services are built.

## CommandPlan And Runbooks

The graph no longer accepts a raw shell string from the LLM. Provider output is
parsed as strict JSON `CommandPlan`; invalid JSON or schema errors are treated
as `BLOCK` and no command is executed.

Built-in runbooks live under `runbooks/`. Each runbook is YAML guidance for
diagnostic procedures. Runbooks do not own fixed natural-language triggers or
scenario phrases, and the graph does not run a matcher before LLM planning.
Every packaged runbook step is policy-evaluated by
`RunbookEngine.evaluate_steps()` during engine construction before the guidance
is considered usable.

The graph injects runbook summaries into the planner prompt as advisory context.
The planner may use, adapt, combine, or ignore that guidance. The output is
still a normal validated `CommandPlan` or `FilePatchPlan`, so policy, HITL,
execution or patch confirmation, audit, and analysis continue through the same
path as other LLM-generated plans.

Remote scope is structured data, not Python natural-language matching:
`commands[].target_hosts` is empty for local execution, contains exact configured
host names or hostnames for selected SSH targets, and uses `["*"]` for every
configured cluster host.

## File Patches And Workspace Tools

Artifact and mutation requests are represented as `FilePatchPlan`, not shell
redirection. `FilePatchPlan.request_intent` carries `create`, `update`, or
`unknown` so safety checks do not infer intent from user-language keywords. The
planner can inspect real state before producing a patch through bounded
read-only tools:

- `read_file(path, offset, limit)`
- `list_dir(path)`
- `search_files(pattern, root)` for literal text search
- `search_logs(pattern, log_file, max_matches)` for literal text search
- `get_system_info()`

All workspace file reads reuse `file_patch.allow_roots`; the default roots are
the current workspace and `/tmp`. Patch application dry-runs unified diffs,
checks allow/high-risk roots before reading targets, validates optional
permission changes, and can relocate hunks when the line number is stale but the
old context matches exactly. The apply path is transactional: symlink path
components, hardlinks, directories, device files, FIFOs, sockets, oversized
targets, and non-UTF-8 text are rejected; writes use temporary files and atomic
replace; existing targets are backed up and rolled back if a later write or
permission change fails. Confirmation rendering shows compact per-file diffs,
`+N / -M` stats, large-diff pagination, high-risk path warnings, permission
changes, and per-file acceptance for multi-file patches.

The planner prompt should preserve existing file style and behavior. If a
requested feature already exists, it should return a no-change answer. If a
request says "create" but the intended target path already exists, the planner
should avoid silently overwriting it by choosing a new filename, returning
no-change, or asking for an explicit conflict decision.

Project-specific code rules are enforced by `make security` and CI through
`scripts/check_code_rules.py`. Module-top `TYPE_CHECKING` imports are allowed;
imports inside functions or methods are not. Optional dependency handling should
stay at module/provider boundaries and raise explicit provider errors when the
extra is not installed.

## Observability And Audit

Every graph run receives a `trace_id` that is attached to HITL audit records
and local telemetry spans. The default telemetry backend writes JSONL to
`~/.linuxagent/telemetry.jsonl`; it does not require an external OTel service.

Audit records are hash-chained with `prev_hash` and `hash`. Use
`linuxagent audit verify` to validate the current audit log and locate the
first tampered line.

## Repository Note

The old `v3` source has been removed. All active work belongs in `src/linuxagent/`.
