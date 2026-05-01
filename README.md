<div align="center">
  <h1>LinuxAgent</h1>
  <img src="logo.jpg" alt="LinuxAgent Logo" width="280" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Eilen6316/LinuxAgent/ci.yml?branch=master&style=flat-square&label=CI" alt="CI"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0"><img src="https://img.shields.io/github/v/release/Eilen6316/LinuxAgent?style=flat-square" alt="Release"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0"><img src="https://img.shields.io/badge/package-GitHub%20Release-blue?style=flat-square" alt="GitHub Release package"></a>
    <a href="README.md#quality-gate"><img src="https://img.shields.io/badge/coverage-87.06%25-brightgreen?style=flat-square" alt="Coverage"></a>
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

For API relays or third-party OpenAI-compatible endpoints, use
`openai_compatible` or a provider shortcut such as `qwen`, `kimi`, `glm`,
`minimax`, `gemini`, or `hunyuan`:

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: gpt-4o-mini
  api_key: "replace-me"
  token_parameter: max_tokens
```

Anthropic-format relays can use `provider: anthropic_compatible` with their own
`base_url`; Xiaomi MiMo can use `provider: xiaomi_mimo`.

Provider quick reference:

| Provider | Protocol | Typical `base_url` | Token parameter |
|---|---|---|---|
| `deepseek` | OpenAI-compatible | `https://api.deepseek.com/v1` | `max_completion_tokens` |
| `openai` | OpenAI | `https://api.openai.com/v1` | `max_completion_tokens` |
| `openai_compatible` | OpenAI-compatible relay | relay-specific `/v1` URL | often `max_tokens` |
| `qwen` | OpenAI-compatible | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `max_tokens` |
| `kimi` | OpenAI-compatible | `https://api.moonshot.ai/v1` | `max_tokens` |
| `glm` | OpenAI-compatible | `https://open.bigmodel.cn/api/paas/v4` | `max_tokens` |
| `minimax` | OpenAI-compatible | `https://api.minimax.io/v1` | `max_tokens` |
| `gemini` | OpenAI-compatible | `https://generativelanguage.googleapis.com/v1beta/openai/` | `max_tokens` |
| `hunyuan` | OpenAI-compatible | `https://api.hunyuan.cloud.tencent.com/v1` | `max_tokens` |
| `anthropic` | Anthropic | provider default | n/a |
| `anthropic_compatible` | Anthropic-compatible relay | relay-specific URL | n/a |
| `xiaomi_mimo` | Anthropic-compatible | relay-specific URL | n/a |

Run:

```bash
linuxagent check
linuxagent
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

For ordinary conversation, LinuxAgent first asks an LLM-owned intent router for
`DIRECT_ANSWER`, `COMMAND_PLAN`, or `CLARIFY`. Direct answers do not create a
command plan and therefore do not show the confirmation panel. Operational
methods are not hard-coded in Python; successful command patterns are learned in
the local learner memory after sensitive values are redacted. Deterministic
safety policy data lives in YAML, while Python code only loads, validates, and
applies those policies.

Each CLI launch starts with an empty conversation context. Saved sessions are
available only when the operator asks for it with `/resume`; then enter the
shown number or use the interactive picker to resume that saved session. If the
selected session stopped at a HITL confirmation, LinuxAgent reloads the local
checkpoint and reopens the confirmation flow. Use `/new` to reset context inside
a running CLI session and `/tools` to see available slash/tool entry points.
Typing `/` opens the slash-command completion menu.
Input beginning with `!` is direct command mode: LinuxAgent executes the
operator-authored command, streams stdout/stderr live, and records both
`!<command>` and the system result into the active conversation context. It does
not ask the LLM to explain or generate a reply for that turn.

## Core Capabilities

| Capability | Why it matters |
|---|---|
| Capability-based policy engine | Produces `SAFE` / `CONFIRM` / `BLOCK`, risk scores, capabilities, and matched rules |
| YAML policy defaults | Command policy data is loaded from `configs/policy.default.yaml`, not Python rule tables |
| Structured `CommandPlan` | LLM output must validate as JSON before any policy or execution path |
| Structured file patches | Script/code/config edits use `FilePatchPlan`, unified-diff validation, path policy, and HITL review |
| Read-only workspace tools | Planner can inspect allowed files with `read_file`, `list_dir`, and `search_files` before proposing patches |
| AI-owned intent routing | Conversation vs operation vs clarification is decided by `prompts/intent_router.md`, not Python keyword rules |
| Explicit resume control | New sessions do not inherit previous chats unless `/resume` is used; pending HITL checkpoints resume there too |
| Direct `!` command mode | Runs operator-authored commands without an AI reply and adds command/output to current context |
| YAML runbooks | Common ops procedures are injected as planner guidance, not pre-LLM hard routes |
| Learner memory | Successful command patterns are persisted locally after secret redaction |
| LangGraph HITL | Confirmation uses `interrupt()` and checkpointing rather than inline `input()` |
| SSH cluster guard | Batch confirmation plus remote shell metacharacter blocking |
| Output protection | Command results are redacted and bounded before model-facing analysis |
| Hash-chained audit | `linuxagent audit verify` detects local audit-log tampering |
| Reproducible release | `constraints.txt`, wheel verification, and packaged config/prompt/runbook checks |

## File Changes

Requests such as "create a shell script", "update this Python file", or "edit
this config" do not bypass the safety model. LinuxAgent asks the planner for a
structured `FilePatchPlan`, then validates and previews the unified diff before
writing anything. The plan carries a structured `request_intent` field
(`create`, `update`, or `unknown`) instead of relying on Python keyword
matching.

The planner can first inspect the environment with read-only tools:

- `read_file(path, offset, limit)` reads a bounded window from an allowed file.
- `list_dir(path)` lists an allowed directory.
- `search_files(pattern, root)` searches literal text under an allowed root.
- `get_system_info`, `search_logs`, and safety-gated `execute_command` provide
  system context when needed.

The terminal shows observable tool activity such as `LinuxAgent is reading
...` / `LinuxAgent is listing ...`. Patch confirmation shows per-file stats,
compact `+` / `-` diff snippets, high-risk path warnings, permission changes,
large-diff pagination, and per-file acceptance for multi-file patches. Full
diffs are not shown twice; extra review prompts appear only when hidden pages
exist.

By default, file patch reads and writes are limited to the current workspace and
`/tmp` through `file_patch.allow_roots`. Sensitive roots such as `/etc` and SSH
key directories are highlighted as high risk, and permission changes such as
`0755` for generated scripts appear explicitly in the confirmation panel.
Automatic patch repair defaults to two rounds and can be tuned with
`file_patch.max_repair_attempts` (`0` disables automatic patch repair).

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

LinuxAgent is **not** an autonomous remediator or a command sandbox. It is intended for controlled operator-in-the-loop use. See [Production Readiness](docs/en/production-readiness.md) and [Threat Model](docs/en/threat-model.md).

## Built-In Runbooks

LinuxAgent v4 ships with eleven YAML runbooks for common diagnostics:

| Runbook area | Examples |
|---|---|
| Disk and filesystem | `df`, top directories, journal usage |
| Ports and networking | listeners, port ownership, connectivity checks |
| Services and logs | systemd status, recent unit logs, error search |
| System health, OS, load, and memory | overall host health, OS release, CPU pressure, memory pressure, OOM clues |
| Containers, packages, and certificates | container status, installed packages, certificate expiry |

Runbooks no longer perform natural-language hard matching before LLM planning.
They are loaded, policy-validated, and supplied to the planner as advisory
examples. The planner may use, adapt, or ignore that guidance based on the
actual request. If it produces a multi-step plan inspired by a runbook, every
step still goes through normal policy, HITL, audit, and analysis flow.

## Quality Gate

Current documented baseline from `make test` on 2026-04-30:

| Gate | Status |
|---|---|
| Unit tests | 396 passing |
| Optional provider compatibility | covered by `make optional-anthropic` when the extra is installed |
| Harness scenarios | 12 HITL / runbook / cluster scenarios |
| Integration smoke tests | 8 passing |
| Coverage | 87.06% (`--cov-fail-under=80`) |
| Static checks | `ruff`, `mypy`, `bandit`, project code-rule checks |
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
| [Quick Start](docs/en/quickstart.md) | Installation and first run |
| [Migration Guide](docs/en/migration-v3-to-v4.md) | v3 to v4 breaking changes |
| [Threat Model](docs/en/threat-model.md) | Assets, trust boundaries, and mitigations |
| [Production Readiness](docs/en/production-readiness.md) | Where LinuxAgent is and is not appropriate |
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
