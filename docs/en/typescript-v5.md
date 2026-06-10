# TypeScript v5 Experimental ReAct Runtime

LinuxAgent is still a Python v4 application in production. The TypeScript v5
work under `ts/` is an experimental ReAct runtime track built beside Python,
with Python remaining the behavior oracle until the cutover gates are met.

The TypeScript runtime is experimental. Python v4 remains the default release runtime until parity gates pass.

Do not treat the TypeScript workspace as the default `linuxagent` runtime yet.
It exists to make the migration measurable: each subsystem lands with tests,
red-line checks, and parity fixtures before it can replace Python behavior.
LangGraph is the old Python runtime implementation detail; the target TS loop
is `@earendil-works/pi-agent-core` plus the LinuxAgent safety kernel.

## Current Scope

The TypeScript workspace currently contains:

| Package | Current status |
|---|---|
| `@linuxagent/contracts` | Shared TypeBox schemas for command plans, file patch plans, policy decisions, audit entries, and runtime events |
| `@linuxagent/policy` | Token/effective-command policy engine with Python fixture parity for the initial corpus |
| `@linuxagent/audit` | Hash-chained JSONL writer and verifier |
| `@linuxagent/sandbox` | Sandbox runner contracts, no-op runner, and fail-closed profile selection |
| `@linuxagent/executor` | argv-based local executor and bounded output redaction |
| `@linuxagent/agent-runtime` | Session permissions, approval defaults, tool gate, executor-backed command tool, prompt loader, planner validation, minimal runtime wrapper, tool-result redaction hook, minimal turn runner, remote approval/audit metadata, file patch runtime tool, memory scope model, advisory memory read path, and pending memory write path |
| `@linuxagent/tui` | Experimental TUI package shell, chat session, direct command routing, approval selector, confirmation renderer, and slash router |
| `@linuxagent/linuxagent-ts` | Experimental CLI package shell |
| `@linuxagent/ssh` | Remote profile validation, remote command guard, and OpenSSH argv manager |

The workspace also includes exported parity fixtures under
`ts/parity/fixtures/`, a TS parity CLI runner under `ts/parity/`, and TS
red-line checks in `scripts/check_ts_redlines.mjs`.

## Runtime Boundary

The TS line follows the same safety rules as Python v4:

- `@earendil-works/pi-agent-core` may drive the ReAct/tool-calling loop, but
  LinuxAgentToolGate remains the first enforcement hook for sensitive tools.
- `@earendil-works/pi-ai` is only a provider/model abstraction; LinuxAgent
  config remains the secret authority.
- `@earendil-works/pi-tui` may render the interactive surface, but audit JSONL
  remains separate from UI events.
- `@earendil-works/pi-coding-agent` is reference-only. Do not import its
  default `bash`, `write`, or `edit` tools as LinuxAgent authority.
- LLM-planned local commands must stay argv-based; no shell-string execution.
- Tool calls must pass the LinuxAgent tool gate before execution.
- pi-agent-core `afterToolCall` observations must be redacted and bounded
  before they can be returned to the model.
- Audit records for approved command, file patch, or SSH actions must be
  appended before the model receives the tool result.
- Sandbox profiles fail closed when no runner can enforce the requested safe profile.
- The no-op runner records `enforced: false`; plain `spawn` is not sandbox enforcement.
- Model-facing command output is redacted and bounded before analysis.
- Prompt templates remain in `prompts/`; TS code loads them through a prompt loader instead of hard-coding them.

The current TS code does not expose a supported CLI and does not replace
`linuxagent`. Future `linuxagent-ts` entry points must remain explicitly
experimental until policy, HITL, audit, sandbox, SSH, file patch, output
redaction, and harness parity are all satisfied for the release scope.

## Development Commands

Install dependencies and run the TypeScript gates from the repository root:

```bash
make ts-install
make ts-check
```

The individual targets are:

```bash
make ts-lint
make ts-type
make ts-test
make ts-security
make ts-parity
```

`make ts-parity` runs the current TS/Python parity runner. It currently checks
the policy fixture corpus, audit verifier tamper detection, sandbox fail-closed
behavior, output redaction behavior, file patch transaction rollback and
runtime path-policy fail-closed behavior, and HITL same-thread/resume-scoped
session permissions, plus SSH strict known-host and remote command guard
behavior. It also verifies the required harness fixture index and an initial
red-team policy slice for protected tree deletion, protected block-device
mutation, network-to-shell, service mutation, and mkfs cases. Keep Python gates
(`make test`, `make security`, `make red-team`, `make harness`, and release
checks) authoritative for the production runtime.

The experimental CLI check command validates explicit local paths and does not
call a model API:

```bash
node ts/apps/linuxagent-ts/dist/src/cli.js check \
  --config ./config.yaml \
  --policy ./configs/policy.default.yaml \
  --audit ~/.linuxagent/audit.log
```

The config file must be private (`chmod 600`). Passing checks exit `0`, failed
checks exit `1`, and usage errors exit `2`.

The experimental audit verifier wraps the TS hash-chain verifier:

```bash
node ts/apps/linuxagent-ts/dist/src/cli.js audit verify ~/.linuxagent/audit.log
```

It exits `0` for a valid log and `1` for missing or invalid logs.

`linuxagent-ts chat --input <text>` exercises the experimental TUI routing
surface for slash commands such as `/new`, `/resume`, and `/tools`. The default
runtime port is still a safe placeholder and does not call a provider yet.
Bang-prefixed input is recognized as direct command mode, but it fails closed
unless a direct command runner is explicitly configured.

## Progress Tracker

| Area | Status |
|---|---|
| Workspace and red-line checker | Landed |
| Shared contracts and Python fixture export | Landed |
| Policy parity engine | Landed for the initial fixture corpus |
| HITL session permissions, approval defaults, and audit hash chain | Landed |
| Local executor, sandbox contracts, output redaction | Landed |
| Tool gate connected to executor-backed command tool | Landed |
| Prompt loading for agent runtime | Landed |
| Planner validation and fake model tests | Landed |
| Minimal runtime wrapper with sequential command tools | Landed |
| Tool result analysis/redaction hook | Landed |
| Minimal runtime behavior tests | Landed |
| Experimental TUI/CLI skeleton | Landed |
| `linuxagent-ts check` implementation | Landed |
| TUI approval selector and confirmation renderer | Landed |
| Slash router | Landed |
| Chat loop shell | Landed |
| Direct command mode | Landed |
| SSH library decision | Landed |
| Remote profile validation | Landed |
| Remote command guard | Landed |
| OpenSSH argv manager | Landed |
| SSH approval/audit metadata integration | Landed |
| FilePatchPlan contract | Landed |
| File patch path policy | Landed |
| File patch diff validator | Landed |
| File patch transaction guard | Landed |
| File patch runtime integration | Landed |
| Memory scope model | Landed |
| Memory read path | Landed |
| Memory write path pending candidates | Landed |
| Policy parity CLI runner | Landed |
| Harness fixture export and required scenario index | Landed |
| Experimental TS CI job | Landed |
| Cutover checklist | Landed; default-runtime switch still requires a separate release change |

When updating TS behavior, update this page and the relevant README/development
links in the same change so public documentation stays aligned with the code.
