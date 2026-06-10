<div align="center">
  <h1>LinuxAgent</h1>
  <img src="logo.jpg" alt="LinuxAgent Logo" width="280" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Eilen6316/LinuxAgent/ci.yml?branch=master&style=flat-square&label=CI" alt="CI"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.1.0"><img src="https://img.shields.io/github/v/release/Eilen6316/LinuxAgent?style=flat-square" alt="Release"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.1.0"><img src="https://img.shields.io/badge/package-GitHub%20Release-blue?style=flat-square" alt="GitHub Release package"></a>
    <a href="docs/en/development.md"><img src="https://img.shields.io/badge/coverage-80%25%2B-brightgreen?style=flat-square" alt="Coverage"></a>
    <a href="SECURITY.md"><img src="https://img.shields.io/badge/security-policy-green?style=flat-square" alt="Security Policy"></a>
  </p>

  <p><strong>A Linux ops CLI where LLM-generated commands must pass deterministic policy and human approval before execution.</strong></p>

  <p>
    <a href="docs/en/quickstart.md">Quick Start</a> ·
    <a href="docs/zh/quickstart.md">中文快速开始</a> ·
    <a href="docs/en/README.md">English manual</a> ·
    <a href="docs/zh/README.md">中文手册</a> ·
    <a href="docs/releases/v4.1.0.md">v4.1.0 release notes</a> ·
    <a href="https://github.com/Eilen6316/LinuxAgent/issues/new?template=user_feedback.yml">share feedback</a>
  </p>
</div>

---

LinuxAgent is not a free-form shell chatbot and not an autonomous remediator. It
lets an LLM propose Linux operations, but execution stays behind deterministic
policy checks, Human-in-the-Loop confirmation, SSH safety guards, output
redaction, and a hash-chained audit log.

The default runtime is Python v4. LangGraph remains the old Python runtime and
rollback anchor. A TypeScript v5 rewrite is in progress under `ts/`, with
`@earendil-works/pi-agent-core` as the target TS ReAct loop, but
`linuxagent-ts` remains experimental until the parity gates in
[TypeScript v5](docs/en/typescript-v5.md) pass and maintainers approve a
separate cutover release.

## Why It Exists

LLM command agents usually fail at the exact point operators care about: trust.
LinuxAgent keeps that trust boundary outside the model.

| Principle | What LinuxAgent does |
|---|---|
| The model is not trusted | First-time LLM-generated commands require confirmation |
| Safety is policy, not substring matching | Commands are tokenized and evaluated by a capability-based policy engine |
| Output may contain secrets | Tool output is guarded and redacted before model-facing analysis |
| SSH must not silently trust hosts | Remote execution uses known-host verification and shell-syntax guards |
| Every approval should be reviewable | HITL decisions are written to a `0o600` hash-chained audit log |

## One-Minute Start

From a source checkout:

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh
```

Create or edit `~/.config/linuxagent/config.yaml`:

```yaml
api:
  provider: deepseek
  api_key: "replace-me"
```

For local Ollama:

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

Then validate and start:

```bash
linuxagent check
linuxagent
```

Try a read-only request:

```text
check the Linux version
```

`config.yaml` must be owned by the current user and `chmod 600`; real secrets
are not loaded from `.env`. More provider paths are in the
[Provider Matrix](docs/en/provider-matrix.md).

## First Confirmation

When a first LLM-generated command appears, LinuxAgent shows the command,
policy result, matched rules, sandbox metadata, and risk summary before
execution.

Choose:

| Choice | Meaning |
|---|---|
| `Yes` / `[y]` | Run this command once |
| `Yes, don't ask again` / `[a]` | Allow the same argv command shape only in this conversation and the same `/resume` thread |
| `No` / `[n]` | Refuse this operation |

Destructive commands, `never_whitelist` policy matches, and SSH batch
operations are never covered by conversation approval. Non-TTY confirmation
requests fail closed.

Use `!uname -a` for operator-authored direct command mode. Use `/resume` to
resume a saved conversation or pending HITL checkpoint, and `/new` to start a
fresh context.

## What A Turn Looks Like

```text
you: find services listening on port 8080

intent        -> LLM classifies the request
plan          -> LLM proposes: ss -tlnp sport = :8080
policy        -> CONFIRM (LLM_FIRST_RUN)
confirm       -> operator approves in terminal
execute       -> subprocess argv, no shell=True
analyze       -> concise operator summary
audit.log     -> hash-chained JSONL decision record
```

The status line keeps active task plans visible during long turns, including
when commands are being confirmed or executed.

## Safety Boundaries

| Operation | Default behavior |
|---|---|
| User-authored read-only command | May run when policy returns `SAFE` |
| First LLM-generated command | `CONFIRM` |
| Conversation-approved LLM command | May skip repeat confirmation only for the same argv command shape in the same conversation thread |
| Destructive command | `CONFIRM` every time; never conversation-whitelisted |
| Command targeting root or protected paths | `BLOCK` when matched by policy |
| SSH batch across two or more hosts | Explicit batch confirmation with target hosts and remote profiles |
| Non-TTY confirmation request | Auto-deny |
| Unknown SSH host | Reject by default |
| Default sandbox runner | Records profile metadata only; no process isolation |
| Enabled safe sandbox profile unavailable | Fail closed before spawning |

LinuxAgent is intended for controlled operator-in-the-loop use. For deployment
boundaries, read [Operator Safety](docs/en/operator-safety.md),
[Threat Model](docs/en/threat-model.md), and
[Production Readiness](docs/en/production-readiness.md).

## Core Capabilities

| Capability | Why it matters |
|---|---|
| Capability-based policy engine | Produces `SAFE` / `CONFIRM` / `BLOCK`, risk scores, capabilities, and matched rules |
| Structured command plans | LLM output must validate before policy or execution paths |
| File patch workflow | Script/code/config edits use reviewed unified diffs and transactional apply |
| Read-only workspace tools | The planner can inspect allowed files before proposing changes |
| Explicit resume control | New sessions do not inherit previous chats unless `/resume` is used |
| Direct `!` command mode | Runs operator-authored commands without an AI-generated reply |
| SSH cluster guard | Batch confirmation, remote shell metacharacter blocking, and remote profile audit |
| Output protection | Command results are redacted and bounded before model-facing analysis |
| Hash-chained audit | `linuxagent audit verify` detects local audit-log tampering |
| Local advisory memory | Optional local memory can guide planning but never changes policy or HITL |
| Read-only MCP prototype | `linuxagent mcp` exposes policy classify and audit verify tools only |

## Install Paths

| Path | Use when |
|---|---|
| `./scripts/bootstrap.sh` | You are working from a source checkout and want `linuxagent` available from any directory |
| `pip install -c constraints.txt https://github.com/Eilen6316/LinuxAgent/releases/download/v4.1.0/linuxagent-4.1.0-py3-none-any.whl` | You want the GitHub Release wheel |
| `pip install linuxagent` | You want the PyPI package after release publication |
| `pip install -e ".[dev]"` | You are developing or running the full local gate |
| `pip install -e ".[anthropic]"` | You need the optional Anthropic provider |

## Documentation

| Start here | Purpose |
|---|---|
| [Quick Start](docs/en/quickstart.md) / [中文快速开始](docs/zh/quickstart.md) | Install, configure, and run the first safe request |
| [Documentation index](docs/README.md) | Main navigation for all long-form docs |
| [English manual](docs/en/README.md) / [中文手册](docs/zh/README.md) | User workflow overview |
| [Provider Matrix](docs/en/provider-matrix.md) | Provider setup paths and compatibility status |
| [Operator Safety](docs/en/operator-safety.md) | Plain-language safety boundaries |
| [Security Policy](SECURITY.md) | Vulnerability reporting and supported versions |
| [Development Guide](docs/en/development.md) | Local validation, architecture boundaries, and contribution checks |
| [TypeScript v5](docs/en/typescript-v5.md) | Experimental rewrite status |
| [Release Notes](docs/releases/v4.1.0.md) | Latest released changes |

## Mirrors And Community

| Link | Notes |
|---|---|
| [GitHub](https://github.com/Eilen6316/LinuxAgent.git) | Primary repository |
| [GitCode](https://gitcode.com/qq_69174109/LinuxAgent.git) | Mirror |
| [Gitee](https://gitee.com/xinsai6316/LinuxAgent.git) | Mirror |
| [QQ Group 281392454](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454) | Community |
| [CSDN intro](https://blog.csdn.net/qq_69174109/article/details/146365413) | Project article |

## License

MIT
