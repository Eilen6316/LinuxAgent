# Operator Safety Model

LinuxAgent is a HITL-first operations control plane, not an autonomous shell
chatbot. The model may propose commands, inspect allowed context, and summarize
results, but execution authority remains with deterministic policy and the
operator.

## What The Model Can Do

- classify intent through prompts
- produce a structured `CommandPlan`
- produce a structured `FilePatchPlan`
- call wrapped tools with bounded, redacted outputs
- summarize command results after redaction

## What The Model Cannot Do Directly

- spawn a local process without the sandbox runner boundary
- skip policy evaluation
- skip first-run confirmation for LLM-generated commands
- add global command allowlists
- silently trust unknown SSH hosts
- write files without a validated file patch plan and HITL confirmation

## Confirmation Semantics

| Choice | Effect |
|---|---|
| `Yes` | Approves this operation once |
| `Yes, don't ask again` | Allows matching commands in the current conversation thread and the same thread after `/resume` |
| `No` | Refuses the operation |

Conversation permissions do not apply to destructive commands, rules marked
`never_whitelist`, SSH batch confirmation, or new conversations.

## Sandbox Boundary

The default configuration uses `sandbox.enabled: false` and `runner: noop`.
That records sandbox metadata but does not isolate the process. Enabling safe
profiles with a runner that cannot enforce them fails closed unless the selected
profile is explicit passthrough.

Remote SSH commands are not protected by local OS sandboxing. Their boundary is
host-key verification, target scoping, least-privilege accounts, remote working
directory policy, sudo allowlists, batch confirmation, and audit.

## Audit And Redaction

HITL decisions and command outcomes are appended to a `0o600` hash-chained
audit log. Command text is intentionally recorded raw for traceability. Other
structured fields and model-facing outputs are redacted where possible.

Operators should still avoid asking LinuxAgent to print secrets. Redaction is a
defense-in-depth layer, not permission to expose credentials.

## Not Suitable For

- unattended destructive remediation
- environments where command output must never reach an external LLM
- multi-tenant terminals where local users are not trusted
- hosts that cannot tolerate operator-reviewed command execution
- SSH fleets without known-host management and least-privilege accounts
