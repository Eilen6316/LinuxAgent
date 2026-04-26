<div align="center">
  <h1>LinuxAgent</h1>
  <img src="logo.jpg" alt="LinuxAgent Logo" width="280" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Eilen6316/LinuxAgent/ci.yml?branch=master&style=flat-square&label=CI" alt="CI"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0"><img src="https://img.shields.io/github/v/release/Eilen6316/LinuxAgent?style=flat-square" alt="Release"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0"><img src="https://img.shields.io/badge/package-GitHub%20Release-blue?style=flat-square" alt="GitHub Release package"></a>
    <a href="README.md#quality-gate"><img src="https://img.shields.io/badge/coverage-90.65%25-brightgreen?style=flat-square" alt="Coverage"></a>
    <a href="SECURITY.md"><img src="https://img.shields.io/badge/security-policy-green?style=flat-square" alt="Security Policy"></a>
  </p>

  <p><strong>A HITL-first Linux ops agent that turns LLM suggestions into policy-checked, audited, operator-approved commands.</strong></p>

  <p>
    <a href="docs/zh/README.md">简体中文完整文档</a> ·
    <a href="docs/en/README.md">Full English manual</a> ·
    <a href="docs/releases/v4.0.0.md">v4.0.0 release notes</a>
  </p>
</div>

---

LinuxAgent is a production-minded CLI for Linux operations. It lets an LLM propose commands, but execution stays behind explicit policy checks, Human-in-the-Loop confirmation, SSH safety guards, output redaction, and a hash-chained audit log.

It is built on **LangGraph**, **LangChain**, and **Pydantic v2**. No local deep-learning stack is required.

## Why It Exists

LLM command agents usually fail at the exact point operators care about: trust.

LinuxAgent's default stance is different:

| Principle | What LinuxAgent does |
|---|---|
| The model is not trusted | First-time LLM-generated commands require confirmation |
| Safety is policy, not substring matching | Commands are tokenized and evaluated by a capability-based policy engine |
| Production output may contain secrets | Tool output is guarded and redacted before LLM-facing analysis |
| SSH must not silently trust hosts | Remote execution uses known-host verification and shell-syntax guards |
| Every approval should be reviewable | HITL decisions are written to a `0o600` hash-chained audit log |

## 30-Second Start

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh
source .venv/bin/activate
```

Then edit `./config.yaml` and set your provider API key:

```yaml
api:
  api_key: "replace-me"
```

Run:

```bash
linuxagent check
linuxagent chat
```

`config.yaml` must be owned by the current user and `chmod 600`; secrets are not loaded from `.env`.

## What a Turn Looks Like

```text
you: find services listening on port 8080

parse_intent  -> LLM proposes: ss -tlnp sport = :8080
safety_check  -> CONFIRM (LLM_FIRST_RUN)
confirm       -> operator approves in terminal
execute       -> asyncio subprocess, no shell=True
analyze       -> concise operator summary
audit.log     -> hash-chained JSONL decision record
```

## Core Capabilities

| Capability | Why it matters |
|---|---|
| Capability-based policy engine | Produces `SAFE` / `CONFIRM` / `BLOCK`, risk scores, capabilities, and matched rules |
| Structured `CommandPlan` | LLM output must validate as JSON before any policy or execution path |
| YAML runbooks | Common ops scenarios can be matched before free-form command generation |
| LangGraph HITL | Confirmation uses `interrupt()` and checkpointing rather than inline `input()` |
| SSH cluster guard | Batch confirmation plus remote shell metacharacter blocking |
| Output protection | Command results are redacted and bounded before model-facing analysis |
| Hash-chained audit | `linuxagent audit verify` detects local audit-log tampering |
| Reproducible release | `constraints.txt`, wheel verification, and packaged config/prompt/runbook checks |

## Safety Model

| Operation | Default behavior |
|---|---|
| User-authored read-only command | May run when policy returns `SAFE` |
| First LLM-generated command | `CONFIRM` |
| Destructive command | `CONFIRM` every time; never session-whitelisted |
| Command targeting root or sensitive paths | `BLOCK` when matched by policy |
| SSH batch across two or more hosts | Explicit batch confirmation |
| Non-TTY confirmation request | Auto-deny |
| Unknown SSH host | Reject by default |

LinuxAgent is **not** an autonomous remediator or a command sandbox. It is intended for controlled operator-in-the-loop use. See [Production Readiness](docs/production-readiness.md) and [Threat Model](docs/threat-model.md).

## Built-In Runbooks

LinuxAgent v4 ships with eight YAML runbooks for common diagnostics:

| Runbook area | Examples |
|---|---|
| Disk and filesystem | `df`, top directories, journal usage |
| Ports and networking | listeners, port ownership, connectivity checks |
| Services and logs | systemd status, recent unit logs, error search |
| Load and memory | CPU pressure, memory pressure, OOM clues |
| Containers and certificates | container status, Docker usage, certificate expiry |

Safe follow-up steps can continue automatically after approval; every step still goes through policy evaluation.

## Quality Gate

The current `v4.0.0` baseline:

| Gate | Status |
|---|---|
| Unit tests | 272 passing |
| Optional Anthropic compatibility | 4 passing |
| Harness scenarios | 12 HITL / runbook / cluster scenarios |
| Integration smoke tests | 8 passing |
| Coverage | 90.65% |
| Static checks | `ruff`, `mypy --strict`, `bandit` |
| Build verification | wheel + sdist + packaged data install check |

Useful commands:

```bash
make test
make lint
make type
make security
make harness
make verify-build
```

## Install Paths

| Path | Use when |
|---|---|
| `./scripts/bootstrap.sh` | You are working from a source checkout |
| `pip install -c constraints.txt https://github.com/Eilen6316/LinuxAgent/releases/download/v4.0.0/linuxagent-4.0.0-py3-none-any.whl` | You want the published GitHub Release wheel |
| `pip install -e ".[dev]"` | You are developing or running the full local gate |
| `pip install -e ".[anthropic]"` | You need the optional Anthropic provider |

## Documentation

| Document | Purpose |
|---|---|
| [Documentation index](docs/README.md) | All long-form docs in one place |
| [docs/zh/README.md](docs/zh/README.md) | Full Chinese manual |
| [docs/en/README.md](docs/en/README.md) | Full English manual |
| [Quick Start](docs/quickstart.md) | Installation and first run |
| [Migration Guide](docs/migration-v3-to-v4.md) | v3 to v4 breaking changes |
| [Threat Model](docs/threat-model.md) | Assets, trust boundaries, and mitigations |
| [Production Readiness](docs/production-readiness.md) | Where LinuxAgent is and is not appropriate |
| [Security Policy](SECURITY.md) | Vulnerability reporting and supported versions |
| [Contributing](CONTRIBUTING.md) | Contribution workflow and review expectations |
| [Changelog](CHANGELOG.md) | Release history |

## Mirrors and Community

| Link | Notes |
|---|---|
| [GitHub](https://github.com/Eilen6316/LinuxAgent.git) | Primary repository |
| [GitCode](https://gitcode.com/qq_69174109/LinuxAgent.git) | Mirror |
| [Gitee](https://gitee.com/xinsai6316/LinuxAgent.git) | Mirror |
| [QQ Group 281392454](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454) | Community |
| [CSDN intro](https://blog.csdn.net/qq_69174109/article/details/146365413) | Project article |

## License

MIT
