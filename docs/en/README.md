<div align="center">
  <h1>LinuxAgent</h1>
  <img src="../../logo.jpg" alt="LinuxAgent Logo" width="320" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent.git"><img src="https://img.shields.io/badge/GitHub-Repository-black?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Eilen6316/LinuxAgent/ci.yml?branch=master&style=flat-square&label=CI" alt="CI"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.1.0"><img src="https://img.shields.io/github/v/release/Eilen6316/LinuxAgent?style=flat-square" alt="Release"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.1.0"><img src="https://img.shields.io/badge/package-GitHub%20Release-blue?style=flat-square" alt="GitHub Release package"></a>
    <a href="../../SECURITY.md"><img src="https://img.shields.io/badge/security-policy-green?style=flat-square" alt="Security Policy"></a>
    <a href="https://gitcode.com/qq_69174109/LinuxAgent.git"><img src="https://img.shields.io/badge/GitCode-Repository-blue?style=flat-square&logo=git" alt="GitCode"></a>
    <a href="https://gitee.com/xinsai6316/LinuxAgent.git"><img src="https://img.shields.io/badge/Gitee-Repository-red?style=flat-square&logo=gitee" alt="Gitee"></a>
    <a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454"><img src="https://img.shields.io/badge/QQ_Group-281392454-brightgreen?style=flat-square&logo=tencent-qq" alt="QQ Group"></a>
    <a href="https://blog.csdn.net/qq_69174109/article/details/146365413"><img src="https://img.shields.io/badge/CSDN-Project_Intro-blue?style=flat-square&logo=csdn" alt="CSDN"></a>
  </p>

  <p><em>LinuxAgent v4.1.0: an LLM-assisted Linux operations CLI with deterministic policy checks and mandatory Human-in-the-Loop approval.</em></p>

  <p>
    <a href="../../README.md">Project homepage</a> ·
    <a href="../zh/README.md">简体中文</a>
  </p>
</div>

---

## What is LinuxAgent

LinuxAgent lets an LLM propose Linux operations, but it does not let the model
act as an autonomous shell. Commands are parsed, classified by deterministic
policy, shown to a human when approval is required, executed without
`shell=True`, redacted before model-facing analysis, and written to a local
audit log.

Use it for:

- Day-to-day inspection: files, logs, ports, resources, service status
- Interactive troubleshooting where the model suggests the next command and the operator decides
- SSH fan-out to configured hosts with explicit batch confirmation
- Environments that need a reviewable local JSONL audit trail

For deeper safety architecture, threat modeling, and v3 migration detail, start
with [Operator Safety](operator-safety.md), [Threat Model](threat-model.md),
and [Migration v3 to v4](migration-v3-to-v4.md).

## Install

### Automated

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh
```

The bootstrap script creates `.venv`, prepares
`~/.config/linuxagent/config.yaml`, creates a `~/.local/bin/linuxagent`
launcher, and writes `LINUXAGENT_CONFIG` to your shell profile. Open a new
shell, or source your shell profile, before starting from another directory.

### Manual

```bash
python3.11 -m venv .venv   # python3.12 is also supported
source .venv/bin/activate
pip install -e ".[dev]"
mkdir -p ~/.config/linuxagent ~/.local/bin
cp configs/example.yaml ~/.config/linuxagent/config.yaml
chmod 600 ~/.config/linuxagent/config.yaml
ln -sf "$PWD/.venv/bin/linuxagent" ~/.local/bin/linuxagent
```

Optional extras:

```bash
pip install -e ".[anthropic]"     # Claude support
pip install -e ".[pyinstaller]"   # single-binary packaging
```

Runtime requirements are Python 3.11 or 3.12 on Linux. macOS is useful for
development; Windows is not supported. SSH cluster mode requires target hosts to
already exist in `~/.ssh/known_hosts`.

## Minimal Configuration

Edit `~/.config/linuxagent/config.yaml` and keep it private:

```yaml
# ~/.config/linuxagent/config.yaml
api:
  api_key: "sk-replace-me"
```

The default provider is DeepSeek. For OpenAI-compatible relays:

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: gpt-4o-mini
  api_key: "sk-replace-me"
  token_parameter: max_tokens
```

For local OpenAI-compatible providers such as Ollama:

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

Validate before first use:

```bash
chmod 600 ~/.config/linuxagent/config.yaml
linuxagent check
```

Common providers include `deepseek`, `openai`, `openai_compatible`, `local`,
`ollama`, `vllm`, `lmstudio`, `qwen`, `kimi`, `glm`, `minimax`, `gemini`,
`hunyuan`, `anthropic`, `anthropic_compatible`, and `xiaomi_mimo`. See the
[Provider Compatibility Matrix](provider-matrix.md) and
[`configs/example.yaml`](../../configs/example.yaml) for full configuration
fields.

## First Run

Start the chat interface:

```bash
linuxagent
```

Try a read-only request:

```text
check the Linux version
```

The first LLM-generated command in a conversation is normally shown for
approval:

```text
linuxagent > find services listening on port 8080

LLM proposes: ss -tlnp sport = :8080
Safety: CONFIRM
Rule: LLM_FIRST_RUN
Allow this operation?
1. Yes
2. Yes, don't ask again in this conversation/resume
3. No
```

`Yes, don't ask again` is scoped to the same conversation thread and the same
thread reopened with `/resume`; it is not global. Direct operator-authored
commands can be run with `!`, for example `!uname -a`.

Useful slash commands:

| Command | Use |
|---|---|
| `/resume` | Resume a saved local session; pending confirmations reopen |
| `/new` or `/clear` | Start an empty conversation in the running CLI |
| `/tools` | Show available slash/tool entry points |
| `/job` | Show approved background jobs |
| `/help` | Show CLI help |
| `/exit` or `/quit` | Exit |

## Safety Rules to Remember

- The model is not trusted: LLM-generated commands must pass deterministic
  policy before execution.
- First-time LLM-generated commands require confirmation, even when the command
  looks safe.
- Destructive commands such as `rm -rf`, `mkfs`, `dd`, and `systemctl stop`
  never enter the conversation whitelist.
- `BLOCK` commands stop before the confirmation node; examples include
  root-filesystem deletion, sensitive paths such as `/etc/shadow`, command
  substitution that hides dangerous work, fork bombs, and invalid shell input.
- Non-interactive runs cannot silently approve `CONFIRM`; they fail closed.
- SSH uses known-host verification and rejects unknown hosts. Remote commands
  are restricted to simple argv-style commands before execution.
- Audit logging cannot be disabled and is written with private permissions.

Security policy lives in [SECURITY.md](../../SECURITY.md),
[`configs/policy.default.yaml`](../../configs/policy.default.yaml), and
`src/linuxagent/policy/`.

## Common Scenarios

### Safe Inspection

```text
linuxagent > list files in the current directory
LLM proposes: ls -la
Safety: CONFIRM, Rule: LLM_FIRST_RUN
```

If you approve with the conversation option, the same argv shape can run again
in that conversation or its `/resume` thread. A new conversation does not inherit
that permission.

### Destructive Request

```text
linuxagent > delete /tmp/old_backup
LLM proposes: rm -rf /tmp/old_backup
Safety: CONFIRM, Rule: DESTRUCTIVE
```

Approval applies only to that execution. The next destructive command prompts
again.

### Blocked Request

```text
linuxagent > wipe the whole system
LLM proposes: rm -rf /
Blocked: destructive command targeting root filesystem
```

The command is rejected by policy before execution or HITL approval.

### SSH Batch Operation

Configure hosts in `cluster.hosts` and keep their host keys in
`~/.ssh/known_hosts`. When a request targets two or more hosts, LinuxAgent shows
a batch confirmation containing the command, matched rule, host list, and remote
profile summary before fan-out.

```yaml
cluster:
  batch_confirm_threshold: 2
  known_hosts_path: ~/.ssh/known_hosts
  hosts:
    - name: web-1
      hostname: 192.0.2.11
      username: ops
      key_filename: ~/.ssh/id_ed25519
```

### File Creation and Editing

For requests such as "create a script" or "edit this config", LinuxAgent uses a
structured file patch workflow instead of asking the model to overwrite files
through shell redirection. The planner may inspect allowed files with read-only
tools, then returns a `FilePatchPlan` with target files, unified diff, risk
summary, and verification commands. The diff is shown before any write, and
approved patches are applied transactionally. Full details are covered in
[Operator Safety](operator-safety.md).

### Interrupt and Resume

Pending confirmation nodes are saved with private permissions. Restart the CLI,
run `/resume`, choose the saved session, and LinuxAgent reopens the pending
approval for the same thread.

## Audit Log

HITL decisions, executions, refusals, and related metadata are appended to
`~/.linuxagent/audit.log` as hash-chained JSONL with `0o600` permissions.

Useful read-only commands:

```bash
linuxagent audit verify
linuxagent audit summary
linuxagent audit inspect --limit 10
linuxagent audit inspect --show-commands
```

`inspect` redacts command details by default. `--show-commands` prints command
text only after the existing redaction rules run.

## Local Memory and Language

Local filesystem memory is advisory context, not a safety boundary. It cannot
lower policy decisions, skip HITL, change sandbox enforcement, execute commands,
or edit audit records. Disable all memory reads and writes with:

```yaml
memory:
  enabled: false
```

The runtime language for LinuxAgent-owned fixed UI text can be set at the top
level:

```yaml
language: en-US  # zh-CN | en-US
```

This does not translate command output, prompt templates, audit field names,
tool names, policy rule ids, or model-generated answers.

## Where to Go Next

| Need | Link |
|---|---|
| Provider setup | [Provider Compatibility Matrix](provider-matrix.md) |
| Operator safety model | [Operator Safety](operator-safety.md) |
| Threat model | [Threat Model](threat-model.md) |
| Production checklist | [Production Readiness](production-readiness.md) |
| Red-team cases | [Red Team](red-team.md) |
| Development workflow | [Development](development.md) |
| Release process | [Release](release.md) |
| v4.1 release notes | [v4.1.0](../releases/v4.1.0.md) |
| Chinese manual | [简体中文](../zh/README.md) |

## FAQ

**`linuxagent check` says the config must be `0600`.**
Run `chmod 600 ~/.config/linuxagent/config.yaml` and make sure the file is owned
by the current user.

**`api.api_key is required`.**
Set `api.api_key` in the active config. After bootstrap this is usually the file
pointed to by `LINUXAGENT_CONFIG`; use `--config ./config.yaml` when you want a
workspace-specific config.

**Can `--yes` skip all confirmations?**
No. Command-level `CONFIRM` and `BLOCK` decisions are safety boundaries. A
non-interactive context auto-denies confirmations instead of approving them.

## License

This project is licensed under the MIT License.
