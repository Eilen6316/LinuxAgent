# Release

## Local Checklist

Run these before tagging:

```bash
make test
make lint
make type
make security
python -m tests.harness.runner --scenarios tests/harness/scenarios
python -m pip check
make verify-build
```

The wheel verification step installs the built wheel and runtime dependencies
in a temporary virtualenv, checks `linuxagent --help`, and verifies packaged
config, prompt, and runbook data are present. It uses PyPI by default; set
`LINUXAGENT_PIP_INDEX_URL` to test against a private mirror.

Optional integration smoke checks:

```bash
make integration
make optional-anthropic  # after pip install -e '.[anthropic,dev]'
```

Run these when the local environment supports the integration assumptions and
optional provider extras. They are not part of the default CI gate.

## Version Narrative

Use the same release positioning everywhere:

> LinuxAgent v4.0.0 is the first formal release of the rewritten operations
> assistant. It replaces the earlier prototype with a LangGraph-based,
> policy-driven, audited CLI for controlled human-in-the-loop Linux operations.

Recommended GitHub About fields:

- Description: `LLM-driven Linux operations assistant CLI with mandatory HITL safety, policy engine, runbooks, SSH guards, and audit trails.`
- 中文描述：`LLM 驱动、强制 HITL、人机确认、策略引擎、Runbook、SSH 防护和审计日志的 Linux 运维 CLI。`
- Website: `https://github.com/Eilen6316/LinuxAgent#readme`
- Topics: `linux`, `ops`, `llm`, `agent`, `langgraph`, `cli`, `hitl`, `runbooks`, `ssh`, `audit`

## Dependency Constraints

`constraints.txt` is generated from the verified release environment and
committed with the release. Use it for reproducible installs:

```bash
pip install -c constraints.txt linuxagent
pip install -c constraints.txt -e ".[dev]"
```

Regenerate before a release after the full gate passes:

```bash
pip-compile pyproject.toml --extra dev --extra anthropic --extra pyinstaller --strip-extras --index-url https://pypi.org/simple --output-file constraints.txt
```

## Expected Artifacts

- `dist/*.whl`
- `dist/*.tar.gz`
- `coverage.xml` and `htmlcov/` from the CI coverage artifact

## Tag Release

```bash
git tag v4.0.0
git push origin v4.0.0
```

The GitHub Actions release workflow builds artifacts and creates a GitHub
Release using `docs/releases/v4.0.0.md` as the release body. The Chinese release
notes live in `docs/zh/releases/v4.0.0.md`.
