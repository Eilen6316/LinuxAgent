<div align="center">
  <h1>LinuxAgent</h1>
  <img src="logo.jpg" alt="LinuxAgent Logo" width="320" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent.git"><img src="https://img.shields.io/badge/GitHub-Repository-black?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Eilen6316/LinuxAgent/ci.yml?branch=master&style=flat-square&label=CI" alt="CI"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0"><img src="https://img.shields.io/github/v/release/Eilen6316/LinuxAgent?style=flat-square" alt="Release"></a>
    <a href="https://pypi.org/project/linuxagent/"><img src="https://img.shields.io/pypi/v/linuxagent?style=flat-square" alt="PyPI"></a>
    <a href="README.md#core-make-targets"><img src="https://img.shields.io/badge/coverage-90.65%25-brightgreen?style=flat-square" alt="Coverage"></a>
    <a href="SECURITY.md"><img src="https://img.shields.io/badge/security-policy-green?style=flat-square" alt="Security Policy"></a>
    <a href="https://gitcode.com/qq_69174109/LinuxAgent.git"><img src="https://img.shields.io/badge/GitCode-Repository-blue?style=flat-square&logo=git" alt="GitCode"></a>
    <a href="https://gitee.com/xinsai6316/LinuxAgent.git"><img src="https://img.shields.io/badge/Gitee-Repository-red?style=flat-square&logo=gitee" alt="Gitee"></a>
    <a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454"><img src="https://img.shields.io/badge/QQ_Group-281392454-brightgreen?style=flat-square&logo=tencent-qq" alt="QQ Group"></a>
    <a href="https://blog.csdn.net/qq_69174109/article/details/146365413"><img src="https://img.shields.io/badge/CSDN-Project_Intro-blue?style=flat-square&logo=csdn" alt="CSDN"></a>
  </p>

  <p><em>LinuxAgent v4.0.0: LLM-driven Linux operations assistant CLI with mandatory Human-in-the-Loop safety.</em></p>
</div>

---

**LinuxAgent** translates plain-language ops requests into Linux commands your team actually wants to run. Every model-generated command is classified at the token level, every side-effecting action needs a human approval, and every decision lands in an append-only audit log.

Built on **LangGraph** + **LangChain** + **Pydantic v2**. No local deep-learning stack required.

**v4.0.0 is the first formal release of the rewritten agent.** It replaces the earlier prototype with a policy-driven, audited, runbook-aware CLI designed for controlled operator-in-the-loop use.

## Language

- [简体中文（完整文档）](README_CN.md)
- [English (full documentation)](README_EN.md)

## At a glance

```
you: find services listening on port 8080

  parse_intent  → LLM proposes: ss -tlnp sport = :8080
  safety_check  → CONFIRM (LLM_FIRST_RUN)
  confirm       → [ y ] Allow this operation?
  execute       → asyncio subprocess (no shell)
  analyze       → "nginx (PID 4312) owns 8080"
  audit.log     → JSONL record of request / decision / execution
```

## Highlights

- **Capability-based policy engine** — `SAFE` / `CONFIRM` / `BLOCK` plus risk scores, capabilities, and matched rules
- **Structured CommandPlan** — model output must be JSON with purpose, preflight, verification, rollback, and side-effect hints
- **Graph-integrated YAML Runbooks** — 8 built-in ops runbooks are matched before LLM command generation; safe follow-up steps can continue after one approval
- **LangGraph state machine** — explicit nodes, conditional edges, `interrupt()`-based Human-in-the-Loop
- **No `shell=True`, no `AutoAddPolicy`** — enforced by CI red-line grep, not just convention
- **Remote SSH shell-syntax guard** — cluster commands reject `;`, pipes, redirects, command substitution, and variable expansion before SSH
- **Hash-chained audit log** at `~/.linuxagent/audit.log`, `0o600`, verifiable with `linuxagent audit verify`
- **Local telemetry JSONL** with per-run `trace_id`, no external collector required by default
- **Resource threshold alerts** for CPU, memory, and root filesystem usage in `linuxagent check`
- **Cluster-aware batch confirmation** — ≥2 hosts triggers an explicit approval prompt
- **272 default unit tests + 4 optional Anthropic compatibility tests + 12 HITL scenarios**, 90%+ coverage, `mypy --strict`, `bandit` clean

## Quick start

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh          # creates .venv, seeds config.yaml (0600)
source .venv/bin/activate

# set your API key in ./config.yaml then:
linuxagent check                # validate config
linuxagent chat                 # start the interactive session
```

Full installation, configuration, and usage walkthroughs live in the localized READMEs:

- [Full README (中文)](README_CN.md) — **recommended**
- [Full README (English)](README_EN.md)

## Why v4 over the earlier prototype

Short version — the older single-file agent had a 4710-line God Object, substring-based command filtering, `AutoAddPolicy` SSH, and zero tests. The current release rewrites all four dimensions:

| Area | Earlier | Current `v4` |
|---|---|---|
| Orchestration | 4710-line agent class, recursive control flow | LangGraph state machine, 72-line coordinator |
| Command classifier | `pattern in command` substring match | Capability-based policy engine with `shlex` token facts, risk score, and source upgrades |
| SSH execution | `AutoAddPolicy` + raw shell strings | `RejectPolicy` + explicit `known_hosts` + remote shell-syntax guard |
| HITL | implicit, bypassable | `interrupt()` + checkpointing + audit log |
| Planning | raw shell string | validated JSON `CommandPlan` |
| Semantic search | hand-rolled TF-IDF, ~500MB local stack | LLM embedding API + disk cache, no local models |
| Tests | 0 | 272 default unit + 4 optional Anthropic compatibility tests + 12 HITL scenarios + 8 integration smoke tests |

See the [full comparison](README_CN.md#与旧版本的全面对比) ([English](README_EN.md#full-comparison-with-the-original-prototype)) for algorithm-level diffs.

## Repository layout

```
src/linuxagent/     active package (src-layout)
src/linuxagent/policy/ capability-based command policy engine
src/linuxagent/plans/  structured CommandPlan schema and parser
src/linuxagent/graph/  LangGraph orchestration split by intent/safety/routing/nodes
src/linuxagent/runbooks/ YAML runbook loader and matcher
src/linuxagent/telemetry.py local JSONL spans and trace IDs
runbooks/           built-in ops runbooks
tests/unit/         unit tests
tests/integration/  optional integration tests (`make integration`)
tests/harness/      YAML scenario harness
configs/            default + example config
prompts/            runtime prompts
docs/               user and release docs
scripts/            bootstrap + verification scripts
```

Runtime policy overrides can be enabled in `config.yaml`:

```yaml
policy:
  path: ~/.config/linuxagent/policy.yaml
  include_builtin: true  # built-ins + user rule overrides/appends
```

## Core make targets

```bash
make test       # pytest with 80% fail-under, currently 90%+
make integration  # optional integration tests
make optional-anthropic  # optional Anthropic extra compatibility
make lint       # ruff
make type       # mypy --strict
make security   # grep red-lines + bandit
make harness    # YAML scenario harness
make build      # wheel + sdist
make verify-build  # build + wheel install + packaged data check
linuxagent audit verify  # verify audit hash chain
```

## Docs

- [Quick Start](docs/quickstart.md)
- [Development Guide](docs/development.md)
- [Release Guide](docs/release.md)
- [Migration Guide: v3 to v4.0.0](docs/migration-v3-to-v4.md)
- [Threat Model](docs/threat-model.md)
- [Production Readiness](docs/production-readiness.md)
- [Release Notes](docs/releases/v4.0.0.md)
- [Changelog](CHANGELOG.md) / [中文更新日志](CHANGELOG_CN.md)
- [Security Policy](SECURITY.md) / [安全政策](SECURITY_CN.md)
- [Contributing](CONTRIBUTING.md) / [贡献指南](CONTRIBUTING_CN.md)
- [Code of Conduct](CODE_OF_CONDUCT.md) / [行为准则](CODE_OF_CONDUCT_CN.md)

## License

MIT
