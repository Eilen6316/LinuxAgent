# TypeScript v5 Progressive Rewrite Design

Status: experimental track, Python v4 remains the release runtime.

The TypeScript runtime is experimental. Python v4 remains the default release runtime until parity gates pass.

## Motivation

LinuxAgent's Python v4 runtime is the current product and safety baseline. The
TypeScript v5 track exists to evaluate whether the runtime can move toward a
typed, package-oriented kernel while keeping the operational safety properties
that make LinuxAgent acceptable for real machines.

The rewrite is progressive instead of big-bang:

- Python remains the behavior oracle and release runtime.
- Each TS package lands with local tests before it is connected to a broader
  runtime path.
- Security-sensitive behavior must have parity fixtures or red-line checks
  before it can be considered for cutover.
- Public docs must keep the TS runtime marked experimental until cutover gates
  pass.

## pi Adoption Boundary

The upstream `earendil-works/pi` packages are useful as implementation
infrastructure, not as a replacement for LinuxAgent's safety model. The TS
track may use pi packages for model/provider abstractions, agent composition,
coding-agent ergonomics, or TUI primitives when they reduce maintenance cost.

LinuxAgent-owned boundaries remain non-negotiable:

| Boundary | Owner |
|---|---|
| Command plan schemas and validation | LinuxAgent contracts |
| Token/effective-command policy decisions | LinuxAgent policy |
| Human approval and thread-scoped permissions | LinuxAgent agent runtime |
| Sandbox profile selection and fail-closed behavior | LinuxAgent sandbox |
| SSH host-key and remote command safety | LinuxAgent SSH layer |
| Audit JSONL, hash chain, and redaction | LinuxAgent audit/security |
| Release cutover decision | LinuxAgent maintainers |

pi code must not introduce direct command execution, silent approval, shell
string execution, host-key trust-on-first-use, unredacted model context, or
secret-bearing environment variables. Any pi integration that touches those
paths must be wrapped by LinuxAgent contracts and tested through LinuxAgent
gates.

## Safety Invariants

The TS runtime must preserve these Python v4 invariants before any release
cutover:

- LLM-generated commands are represented as argv or structured plans before
  execution; no `shell: true` or string shell execution path is allowed.
- Policy uses token/effective-command analysis, not substring matching.
- First-run LLM commands require Human-in-the-Loop confirmation.
- Destructive commands are never eligible for conversation whitelisting.
- Non-TTY approval requests fail closed.
- Sandbox profiles that cannot be enforced fail closed before spawning.
- The no-op sandbox runner must report `enforced: false`.
- SSH rejects unknown host keys by default and must not enable TOFU bypasses.
- Model-facing command output and audit/tool previews are redacted and bounded.
- Prompt templates live in `prompts/` and are loaded, not hard-coded.
- Audit records remain durable JSONL records and do not get replaced by UI or
  telemetry runtime events.

## Parity Strategy

Parity is built in layers:

1. **Fixture export.** Python exports selected policy and harness fixtures into
   `ts/parity/fixtures/` with deterministic JSONL records.
2. **TS package tests.** Each TS package owns unit tests for its local contract.
3. **Parity runner.** `make ts-parity` runs the TS parity CLI. It currently
   checks policy fixtures and prints audit, harness, and red-team placeholders
   while those suites are expanded.
4. **Experimental CI.** CI runs a separate `ts-experimental` job with
   `make ts-install`, `make ts-check`, and `make ts-parity`.
5. **Promotion only after stability.** TS parity must be green over repeated CI
   runs before any job becomes release-blocking or any TS runtime path replaces
   Python behavior.

Python gates stay authoritative during this phase:

- `make test`
- `make security`
- `make red-team`
- `make harness`
- `make verify-build`

## Cutover Gates

TS can only become a default release runtime after all gates below are true:

| Gate | Requirement |
|---|---|
| Policy parity | TS and Python agree on release-scope policy decisions, matched rules, capabilities, and whitelist eligibility |
| HITL parity | Interrupt/approval behavior matches Python for first-run, resume, non-TTY, and never-whitelist cases |
| Audit parity | TS writes and verifies compatible redacted hash-chained JSONL records |
| Sandbox parity | Safe profiles fail closed without an enforcing runner and report enforcement metadata consistently |
| SSH parity | Host-key policy, remote command guarding, batch metadata, and approval/audit payloads match Python boundaries |
| File patch parity | Structured plan validation, diff preview, path policy, transaction rollback, approval, and audit match Python release scope |
| Output parity | Model-facing command/tool output is redacted and bounded before analysis |
| Harness parity | Selected YAML harness behaviors are represented by TS parity cases or equivalent runtime tests |
| Documentation | README and docs still describe Python as default until the final cutover commit |
| Release gate | Maintainers explicitly promote TS after repeated green CI and a rollback-tested release candidate |

Until every gate passes, TS remains experimental and Python v4 remains the
default `linuxagent` runtime.

## Rollback Strategy

Rollback must be boring:

- Keep Python v4 code and packaging intact while TS runs experimentally.
- Do not remove Python CI jobs or release checks during TS development.
- Keep TS runtime entry points opt-in and clearly named, such as
  `linuxagent-ts`, until cutover.
- If a TS gate regresses, revert or disable the TS entry point without changing
  the Python release path.
- If a promoted TS release fails after cutover, publish a patch release that
  restores Python as default and leaves TS behind an experimental flag.
- Preserve fixture exporters so a rollback can still compare the failed TS
  behavior against Python for root-cause analysis.

The desired end state is not "TS at any cost." The desired end state is a
runtime that preserves LinuxAgent's command-safety guarantees with lower
long-term maintenance risk.
