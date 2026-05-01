# Security Policy

LinuxAgent executes Linux commands proposed by an LLM-driven workflow. Security
reports are treated as high priority, especially issues that affect command
execution, SSH behavior, audit integrity, configuration secrecy, or output
redaction.

## Supported Versions

| Version | Supported |
|---|---|
| 4.0.x | Yes |
| 3.x and earlier | No |

## Reporting a Vulnerability

Please do not open a public issue for a suspected vulnerability.

Preferred reporting path:

1. Use GitHub private vulnerability reporting for this repository, if available.
2. If private reporting is unavailable, contact the maintainer through the
   repository owner profile and include `LinuxAgent security report` in the
   subject.

Include:

- A concise description of the issue and affected version or commit.
- Reproduction steps, including the exact command or prompt if relevant.
- Expected impact: command bypass, secret exposure, audit tampering, SSH trust
  issue, denial of service, or another category.
- Any logs or outputs with secrets removed.

## Response Targets

| Severity | Examples | Target |
|---|---|---|
| Critical | Silent command execution, HITL bypass, arbitrary destructive execution | Initial response within 48 hours |
| High | Secret leakage to LLM/tool output, SSH host-key bypass, audit hash-chain bypass | Initial response within 72 hours |
| Medium | Incorrect BLOCK/CONFIRM classification, local permission weakness | Initial response within 7 days |
| Low | Documentation or hardening gap with limited exploitability | Best effort |

## Security Boundaries

LinuxAgent is designed as a human-confirmed operations assistant. Sandbox
profiles constrain impact after policy and HITL, but they do not grant
execution authority and do not make blocked commands safe.
The project assumes:

- The local user account is trusted to approve or reject operations.
- `config.yaml` is local, owned by the current user, and `chmod 600`.
- Unknown SSH hosts are not trusted by default.
- Commands are still executed with the privileges of the invoking user.
- Remote SSH targets are protected through least-privilege accounts, sudo
  allowlists, host-key verification, batch confirmation, and audit rather than
  local OS sandbox inheritance.

## Security Review Checklist

For changes touching execution, tools, file patches, SSH, audit, or sandbox
runners, reviewers should check:

- sandbox bypass: local process creation still goes through `SandboxRunner`.
- tool wrapping: every LLM-facing LangChain tool has `ToolSandboxSpec` metadata
  and model-facing output redaction.
- fallback behavior: no-op and passthrough paths report `enforced=false`; safe
  profiles fail closed when the selected runner cannot enforce them.
- audit completeness: sandbox, file patch, and SSH remote metadata are recorded
  where applicable.
- package data: `make verify-build` confirms config, policy, prompts, runbooks,
  and sandbox config sections are present in the wheel.

See [Threat Model](docs/en/threat-model.md) and
[Production Readiness](docs/en/production-readiness.md) for operational guidance.
