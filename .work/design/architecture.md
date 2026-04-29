# LinuxAgent v4 Architecture

> Source of Truth for the v4 runtime architecture. Implementation plans live in
> `.work/plan/`; coding rules live in `.work/rule/`; prompt templates live in
> `prompts/`.

## Current Status

- Package: `linuxagent`
- Version: `4.0.0`
- Classifier: `Development Status :: 5 - Production/Stable`
- Runtime target: Python 3.11+
- Primary stack: LangGraph, LangChain Core, Pydantic v2, YAML policy/runbook data

`pyproject.toml` is the authoritative source for package metadata, dependency
ranges, entry points, and packaged data.

## Product Boundary

LinuxAgent is a HITL-first Linux operations assistant CLI. The LLM may classify
intent, produce plans, and summarize results, but command execution is guarded by:

- structured `CommandPlan` validation
- token-level policy evaluation
- Human-in-the-Loop confirmation
- per-session command allowlisting
- output redaction before analysis prompts
- audit and telemetry records
- SSH host-key verification for remote execution

The product is not a free-form shell chatbot. It is an operations control plane
where LLM planning remains behind deterministic policy and approval gates.

## Runtime Flow

1. User input enters the app service.
2. The graph calls the intent router prompt.
3. Direct answer or clarification requests return without command planning.
4. Operational requests call the planner prompt.
5. The planner returns a JSON `CommandPlan`.
6. The graph validates the plan with Pydantic.
7. The current command is evaluated by the policy engine.
8. `SAFE` commands may execute; `CONFIRM` commands interrupt for HITL approval;
   `BLOCK` commands stop with the policy reason.
9. Execution results are redacted before LLM analysis.
10. Multi-step plans continue through the same policy and HITL gates for every
    command.

## Module Boundaries

| Area | Path | Responsibility |
|---|---|---|
| CLI and app orchestration | `src/linuxagent/cli.py`, `src/linuxagent/app/` | User session loop and high-level agent service |
| Dependency wiring | `src/linuxagent/container.py` | Runtime construction for config, provider, graph, policy, runbooks, telemetry |
| LangGraph runtime | `src/linuxagent/graph/` | Intent routing, planning, safety nodes, execution routing, analysis |
| Plans | `src/linuxagent/plans/` | `CommandPlan` schema and JSON parsing |
| Policy | `src/linuxagent/policy/`, `configs/policy.default.yaml` | Capability/risk-based command decisions |
| Executors | `src/linuxagent/executors/` | Local command execution using argv semantics |
| Cluster | `src/linuxagent/cluster/` | SSH connection management and remote command execution |
| Runbooks | `src/linuxagent/runbooks/`, `runbooks/` | YAML runbook loading and policy validation |
| Prompts | `prompts/`, `src/linuxagent/prompts_loader.py` | Prompt templates and template loading |
| UI | `src/linuxagent/ui/` | Console rendering and HITL payload display |
| Telemetry and audit | `src/linuxagent/telemetry.py`, `src/linuxagent/audit.py` | Runtime event and decision records |
| Harness | `tests/harness/`, `tests/integration/` | Offline behavior scenarios and graph integration checks |

New production code belongs under `src/linuxagent/`. Legacy v3 code is not part
of the v4 architecture boundary.

## Prompt Ownership

Prompt templates are source files under `prompts/`:

- `system.md`
- `chat.md`
- `direct_answer.md`
- `intent_router.md`
- `planner.md`
- `repair.md`
- `analysis.md`

Python code must load these templates through `src/linuxagent/prompts_loader.py`.
Python modules must not embed planner schemas, runbook policy text, artifact
planning rules, or repair prompts as large string literals. This keeps prompt
changes reviewable and prevents split-brain prompt behavior.

## Intent Routing

Intent routing is LLM-owned. Python code should not hard-code natural-language
trigger phrases to decide whether a user request is a direct answer, a
clarification, or an operational plan.

The router decides the broad mode. The planner then produces a validated
`CommandPlan` for operational work.

## CommandPlan

Operational output from the LLM must be a JSON `CommandPlan`. The graph rejects
invalid JSON or schema-invalid plans before policy or execution.

The plan can contain multiple commands. Each command is still evaluated
independently by policy and confirmation logic before execution. A previous
approval does not bypass policy for later commands.

Artifact and mutation requests, including shell scripts, Python or Go programs,
Ansible playbooks, config files, and crontab entries, use normal `CommandPlan`
planning. They are not captured by runbook routing.

When an artifact depends on runtime or toolchain details, the plan should include
environment/version discovery before generating files or verification commands.
Examples include Python version, Go version, package manager, shell, OS release,
available CLIs, and target paths.

## Runbooks

Runbooks are structured operational guidance, not natural-language routers.

Current runbook behavior:

- YAML runbooks do not define fixed `triggers` or `scenarios`.
- The graph does not auto-match and execute a runbook before LLM planning.
- Runbook summaries are injected into the planner as advisory context.
- Planner output still goes through `CommandPlan` validation.
- Every planned command still goes through policy and HITL gates.
- `RunbookEngine` validates loaded runbook steps against policy at construction
  time so packaged guidance fails fast if a read-only step violates policy.

This preserves runbooks as curated operational knowledge without letting them
preempt user requests or suppress the planner's environment reasoning.

## Policy

Policy evaluation is token-based and capability-oriented. Built-in policy data
is maintained in `configs/policy.default.yaml`; runtime policy loading and
merging are implemented under `src/linuxagent/policy/`.

Policy decisions expose:

- level: `SAFE`, `CONFIRM`, or `BLOCK`
- reason
- risk score
- capabilities
- matched rules
- approval requirements

The graph treats policy as the execution gate for both LLM-planned commands and
runbook-guided commands.

## Execution

Local execution uses parsed argv semantics and does not rely on shell execution.
Remote execution uses the SSH subsystem and remains behind the same planning,
policy, confirmation, audit, and telemetry gates.

Cluster host resolution is handled by the cluster service. Tests and examples
must use documentation IP ranges such as `192.0.2.0/24`, `198.51.100.0/24`, or
`203.0.113.0/24` instead of real private infrastructure addresses.

## HITL And Audit

LLM-generated commands require confirmation on first execution unless policy
blocks them. Session allowlists are process-local and do not apply to destructive
commands.

Human decisions and command outcomes are written to the audit log. Telemetry spans
cover the main graph and runtime events, including LLM calls, policy evaluation,
HITL, command execution, SSH execution, runbook validation, and analysis.

## Testing And CI

The expected local gates are:

- `make lint`
- `make type`
- `make test`
- `make integration`
- `make security`
- `make harness`
- `make verify-build`

CI must run unit, integration, security, harness, and build verification so graph
regressions are caught before merge.

Integration tests are the guardrail for multi-node graph behavior, including
intent routing, planner prompt consumption, runbook guidance, and HITL
interrupt/resume behavior.

## Packaging

The wheel includes default config, policy, prompt, and runbook data through
`pyproject.toml` force-include entries. Packaged runtime lookup should work both
from an editable checkout and from installed package data.

## Architecture Principles

- Keep LLM freedom in planning, not in execution authority.
- Keep prompts as files, not Python literals.
- Keep runbooks as guidance, not keyword-triggered control flow.
- Keep every command behind deterministic policy.
- Keep artifact generation environment-aware.
- Keep graph behavior covered by integration tests, not only unit tests.
