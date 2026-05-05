# Roadmap

LinuxAgent is a HITL-first Linux operations control plane. The model may plan
and explain, but execution stays behind deterministic policy, operator
approval, audit, sandbox metadata, and SSH guardrails.

This roadmap is intentionally conservative. Changes that weaken command
approval, host-key verification, auditability, output redaction, or sandbox
boundaries are out of scope unless they first receive a security review.

## Current Priorities

| Priority | Area | Outcome |
|---|---|---|
| P0 | Release hardening | PyPI Trusted Publishing, repeatable release checklist, artifact verification |
| P0 | User onboarding | One-minute quickstart, provider matrix, clearer safety boundaries |
| P1 | Runbook ecosystem | Authoring guide, schema examples, more read-only diagnostics |
| P1 | Provider compatibility | Verified configs for common OpenAI-compatible and local endpoints |
| P1 | Production evidence | Documented smoke tests on common Linux distributions |
| P2 | Observability | More useful trace summaries and audit inspection commands |
| P2 | Packaging | Optional standalone binaries after the wheel path remains stable |

## Good First Issues

These tasks are suitable for new contributors because they are scoped, testable,
and do not require changing command execution semantics.

| Label | Task |
|---|---|
| `good first issue` | Add a read-only runbook for a common diagnostic workflow |
| `good first issue` | Add provider setup notes to `docs/en/provider-matrix.md` after testing a real endpoint |
| `docs` | Improve examples in the one-minute quickstart |
| `docs` | Add a production smoke-test transcript for a Linux distribution |
| `tests` | Add regression cases for policy YAML parsing or runbook validation |
| `tests` | Add CLI smoke coverage for slash commands that do not require a real LLM |

## Areas Requiring Maintainer Review

Open an issue before starting work in these areas:

- command policy levels or `never_whitelist` behavior
- HITL confirmation and conversation permissions
- subprocess, sandbox, SSH, or file patch execution paths
- audit log format and hash-chain behavior
- provider abstraction changes that add a new SDK
- any change that sends more local data into LLM context

## Not Planned

- fully autonomous remediation without operator confirmation
- global command allowlists shared across conversations
- accepting unknown SSH host keys automatically
- replacing deterministic command policy with model-only judgment
- local deep-learning model stacks as runtime dependencies
