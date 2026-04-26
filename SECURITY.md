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

LinuxAgent is designed as a human-confirmed operations assistant, not a sandbox.
The project assumes:

- The local user account is trusted to approve or reject operations.
- `config.yaml` is local, owned by the current user, and `chmod 600`.
- Unknown SSH hosts are not trusted by default.
- Commands are still executed with the privileges of the invoking user.

See [Threat Model](docs/threat-model.md) and
[Production Readiness](docs/production-readiness.md) for operational guidance.
