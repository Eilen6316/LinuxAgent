# Development

## Architecture

The active codebase is the `v4` rewrite under `src/linuxagent/`.

Core layers:

- `config/`: validated application configuration
- `providers/`: LangChain-backed LLM providers
- `executors/`: safe local command execution
- `policy/`: capability-based command policy engine
- `plans/`: strict JSON CommandPlan models and parsing
- `cluster/`: SSH execution and host policy
- `graph/`: LangGraph orchestration split into intent parsing, safety checks, routing, and node factories
- `services/`: application services
- `telemetry.py`: local JSONL spans and trace correlation
- `usage_insights/`: learner, semantic helpers, recommendations
- `ui/`: terminal UI

## TypeScript Experimental Workspace

The `ts/` workspace is the TypeScript v5 experimental rewrite track. It is not
the production runtime and does not replace the default `linuxagent` command.
Python v4 remains the behavior oracle while TS subsystems land behind parity
fixtures and red-line checks.

Current TS packages cover contracts, policy parity, audit hash chains, sandbox
runner contracts, argv-based local execution, output redaction, tool gate
integration, session permissions, approval defaults, and prompt loading. See
[TypeScript v5 Experimental Kernel](typescript-v5.md) for the current progress
tracker and migration boundaries.

Useful TS commands:

```bash
make ts-install
make ts-lint
make ts-type
make ts-test
make ts-security
make ts-check
```

When changing TS behavior, update the TS status document and any relevant
README entry in the same change. Keep Python production gates authoritative
until an explicit cutover checklist is satisfied.

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

Runtime i18n is intentionally limited to LinuxAgent-owned fixed user-facing
text. Do not localize prompt templates, planner guidance, tool descriptions
that enter model context, MCP protocol metadata, audit JSON keys, policy ids,
or other machine-readable fields. `src/linuxagent/i18n/locales/*.yaml` is for
CLI/TUI labels, slash help, confirmation/block messages, diagnostics, and
display-only metadata. New user-visible fixed strings should use a locale key;
new model-visible instructions belong in `prompts/`, policy YAML, Skill
manifests, or the relevant structured data source.

## Runtime Lifecycle Vocabulary

LinuxAgent runtime UX work uses these terms consistently:

| Term | Meaning | Current owner |
|---|---|---|
| turn | One user request handled against one graph thread/checkpoint | `src/linuxagent/app/agent.py`, `src/linuxagent/graph/runtime.py` |
| runtime event | A structured, non-audit status signal emitted while a turn or tool is running | `src/linuxagent/graph/events.py`, `src/linuxagent/runtime_events.py` |
| tool event | A tool-runtime event emitted by LLM-visible tools and the provider tool loop | `src/linuxagent/providers/base.py`, `src/linuxagent/tools/sandbox.py` |
| work item | One visible unit of runtime work such as command execution, a tool call, a worker, or a background job | current dict events; typed model pending |
| pending request | A resumable human decision or input request, currently represented by LangGraph interrupts | `src/linuxagent/graph/*confirm*.py`, `src/linuxagent/ui/interrupt_dispatcher.py` |
| active view | Transient in-terminal state shown while a turn is running | `src/linuxagent/ui/working_status.py` |
| history | Durable conversation output after the active view is cleared or consolidated | chat history and graph messages |
| steer input | User input entered while a turn is still running | not yet first-class |
| cancellation token | Shared cancellation state for a running turn and its child work | not yet first-class |

Current runtime events are legacy dictionaries. Graph nodes emit high-level
`activity` events through `notify_event()`. Read-only batches and direct-answer
workers emit `worker_group` events through `src/linuxagent/runtime_events.py`.
Command batches, background jobs, and streaming command output use related dict
events consumed by the app runtime observer.

Runtime events have three separate consumers:

- telemetry: `src/linuxagent/app/runtime_telemetry.py` records selected event
  types as local telemetry spans.
- UI activity: `src/linuxagent/app/runtime_messages.py`,
  `src/linuxagent/container.py`, and `src/linuxagent/ui/working_status.py`
  turn events into transient terminal status.
- harness: `tests/harness/runner.py` collects `runtime_events` and `tool_events`
  for scenario assertions.

Tool events are separate from runtime events today. The container records tool
audit metadata through `AuditLog.record_tool_event()` and also renders a
transient UI activity message. Tool-event arguments and output previews must
stay redacted before they reach telemetry, UI, or model context.

Audit records are not runtime events. HITL decisions, command execution audit,
file patch audit, and tool audit entries remain durable security records with
their own schema and retention behavior. Runtime events are UI/telemetry/replay
signals and must not replace audit records.

Known gaps before the typed lifecycle work:

- there is no typed `turn_started` / `turn_completed` / `turn_aborted` envelope.
- active terminal state is rendered directly from messages rather than a pure
  active-view reducer.
- cancellation exists at graph-invocation/UI edges but is not a shared runtime
  token.
- busy user input and pending human requests are not represented by one queue
  or request protocol.
- harness event assertions still observe legacy dict events rather than a
  stable typed event contract.

Phase 1 lifecycle acceptance should use this vocabulary when naming harness
scenarios and event assertions, so tests check protocol states rather than
English or Chinese UI prose.

## Architecture Stabilization Track

The current stabilization track is focused on reducing orchestration complexity
before adding more product surface. During this track, feature work should be
deferred unless a maintainer explicitly interrupts the sequence.

Work must stay one subplan scoped: do not mix graph boundary work, node splits,
file patch engine movement, sandbox wording, and container wiring in the same
change. Behavior-preserving refactors must not change prompt templates,
planner schemas, policy decisions, HITL semantics, audit JSON fields, or CLI
UX.

Baseline hotspots being reduced:

| Module | Current responsibility | Intended owner after stabilization |
|---|---|---|
| `src/linuxagent/graph/intent.py` | Intent routing, direct answer, planner gate, tool planning, parse repair, wizard gates | Facade plus focused router, direct-answer, planner, tool-loop, no-change, and repair modules |
| `src/linuxagent/graph/nodes.py` | Confirmation, permissions, execution, batching, plan advancement, analysis | Facade plus focused confirm, permission, execution, batch, plan-step, and analysis modules |
| `src/linuxagent/graph/file_patch_nodes.py` | File patch confirmation, apply, verification, repair | Facade plus focused file patch graph-node modules |
| `src/linuxagent/plans/file_patch.py` | File patch models, parsing, safety, diff apply, transactions, summaries | Public facade plus focused implementation modules under `plans/` |
| `src/linuxagent/graph/state.py` | Broad graph state contract | Documented section contracts with producer/consumer ownership |
| `src/linuxagent/container.py` | Provider, service, tool, UI, graph, and telemetry wiring | Public composition root delegating to focused wiring helpers |

Execution order for the first phase is:

1. stabilization inventory and baseline gates
2. `GraphRuntime` adapter boundary
3. architecture boundary checks for raw LangGraph leakage
4. `AgentState` section contracts
5. intent and planner splits
6. command confirmation/execution splits
7. file patch graph and engine splits
8. sandbox product-contract visibility

The app layer must consume graph execution through `GraphRuntime`; raw LangGraph
resume commands, interrupt extraction, checkpoint snapshots, and snapshot task
inspection belong under `src/linuxagent/graph/`. Service and tool modules must
also stay LangGraph-free. `make security` and CI run
`scripts/check_arch_boundaries.py` to guard these boundaries.

### Architecture Stability Budget

`make security` and CI also run `scripts/check_architecture_budget.py`. The
budget turns the stabilization track into a regression gate:

- `src/linuxagent/app/agent.py` remains capped at 300 physical lines.
- Graph modules default to 430 physical lines. Existing larger modules have
  narrow per-file caps so they cannot grow without an explicit follow-up split.
- Safety-sensitive plan modules default to 260 physical lines, with a narrow
  cap for the existing public plan model facade.
- All Python functions remain capped at 50 physical lines.
- Any new `AgentState` field must be listed in `graph/state_contracts.py` with
  an owner section.
- Any new graph node factory must be added to the budget coverage manifest with
  a real unit test and a harness or boundary scenario.

Tool sandbox metadata and subprocess ownership are enforced by
`scripts/check_sandbox_rules.py`, which is part of the same security gate.

## Security Red Lines

These are enforced both locally and in CI:

- no `shell=True`
- no `AutoAddPolicy`
- no bare `except:`
- no `input()` calls inside `src/linuxagent/graph/`
- no raw LangGraph runtime access from `src/linuxagent/app/`, `services/`, or
  `tools/`
- no direct subprocess creation outside `src/linuxagent/sandbox/`
- no unwrapped LangChain tools exposed to the LLM

`make security` runs `scripts/check_code_rules.py`,
`scripts/check_arch_boundaries.py`, `scripts/check_sandbox_rules.py`,
`scripts/i18n_audit.py`, grep red-lines, and Bandit. The i18n audit fails on
unregistered Chinese runtime string literals in production source. English
phrase detection remains report-only because many English literals are protocol
strings, exception messages, model-facing instructions, or test fixtures.

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
- packaging: `make verify-build` confirms config, policy, prompts,
  locale catalogs, and sandbox config sections are present in the wheel; the
  isolated wheel install also checks `zh-CN` / `en-US` locale key parity.

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

## Network Policy

The top-level `network` config is reserved for application-level LLM/web tools.
Plan 10 only defines configuration, deterministic domain evaluation, audit
event shape, and `linuxagent check` visibility; it does not add fetch/search
tools or perform DNS resolution. Domain rules are normalized to lowercase,
strip one trailing dot, and may use `.example.com` / `*.example.com` for
subdomains only. Deny entries take priority over allow entries.

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

For argument-sensitive rules, prefer `match.argv` so the policy can express
fixed prefixes, exact arity, token positions, and flags that take values without
falling back to substring checks:

```yaml
match:
  argv:
    - prefix: [git, status]
      exact: true
    - prefix: [journalctl]
      flag_values:
        - flag: --unit
          values: [nginx]
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

## CommandPlan

The graph no longer accepts a raw shell string from the LLM. Provider output is
parsed as strict JSON `CommandPlan`; invalid JSON or schema errors are treated
as `BLOCK` and no command is executed.

Multi-step operations are represented as normal validated `CommandPlan`
entries. The graph advances through those entries generically; each command
still goes through policy, HITL, execution or patch confirmation, audit, and
analysis through the same path as any other LLM-generated plan.

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
For development you can set `telemetry.exporter: console` to print redacted span
JSON to stdout. For collector integration set `telemetry.exporter: otlp` and
`telemetry.otlp_endpoint` to an HTTP traces endpoint. Network telemetry export is
never enabled by default.

HITL "allow all" decisions are recorded as `decision: yes_all` with a
Claude-style `permissions.allow` list such as `Bash(cat /etc/os-release)`.
Those permissions live in LangGraph state for the current conversation thread
and the same thread after `/resume`. They match exact argv token shapes rather
than substrings, are not global executor permissions, and are still blocked by
`never_whitelist`, destructive capabilities, SSH batch confirmation, policy,
and sandbox gates.

Audit records are hash-chained with `prev_hash` and `hash`. Use
`linuxagent audit verify` to validate the current audit log and locate the
first tampered line.

## Repository Note

The old `v3` source has been removed. All active work belongs in `src/linuxagent/`.
