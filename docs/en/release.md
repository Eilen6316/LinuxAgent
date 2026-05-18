# Release

LinuxAgent publishes two release surfaces from a signed tag:

- GitHub Release artifacts: wheel and sdist attached to the release.
- PyPI package: published by GitHub Actions through PyPI Trusted Publishing.

## Maintainer Setup

Before the first PyPI release, configure PyPI Trusted Publishing for:

| Field | Value |
|---|---|
| PyPI project | `linuxagent` |
| Owner | `Eilen6316` |
| Repository | `LinuxAgent` |
| Workflow | `release.yml` |
| Environment | `pypi` |

The workflow uses GitHub OIDC (`id-token: write`) and does not require a PyPI
API token secret.

## Local Checklist

Run these before tagging:

```bash
make release-preflight
```

`make release-preflight` checks version consistency, lint, type checking,
security red-lines, unit tests, sandbox tests, integration tests, red-team
policy tests, the YAML harness, and build verification. Run it from a clean
worktree on the release branch.

The release check validates that `pyproject.toml`, `src/linuxagent/__init__.py`,
`CHANGELOG.md`, Chinese changelog, and release notes all point at the same
version. For a tag dry-run, use:

```bash
python scripts/release_check.py --versions --tag v4.1.0
```

The artifact verification step builds wheel and sdist, checks wheel/sdist
metadata, rejects `.work/`, local `config.yaml`, cache, and bytecode files, then
installs the built wheel in a temporary virtualenv. It checks
`linuxagent --version`, `linuxagent --help`, `linuxagent check`, and packaged
config, policy, prompt, and locale data. The isolated wheel install
also validates that packaged `zh-CN` / `en-US` locale catalogs load and have
key parity. It uses PyPI by default; set `LINUXAGENT_PIP_INDEX_URL` to test
against a private mirror.

For slow mainland China networks, run the same gate through a domestic mirror:

```bash
LINUXAGENT_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
LINUXAGENT_PIP_TIMEOUT=120 \
make verify-build
```

Optional integration smoke checks:

```bash
make integration
make optional-anthropic  # after pip install -e '.[anthropic,dev]'
```

Run the optional provider extra when the local environment supports it. The
standard integration suite is part of `make release-preflight`.

## Version Narrative

Use the same release positioning everywhere:

> LinuxAgent v4.1.0 is a security-depth release. It turns the v4 command safety
> boundary into something easier to attack, measure, verify, and reuse from
> other agent clients.

Recommended GitHub About fields:

- Description: `LLM-driven Linux operations assistant CLI with mandatory HITL safety, policy engine, SSH guards, and audit trails.`
- 中文描述：`LLM 驱动、强制 HITL、人机确认、策略引擎、SSH 防护和审计日志的 Linux 运维 CLI。`
- Website: `https://github.com/Eilen6316/LinuxAgent#readme`
- Topics: `linux`, `ops`, `llm`, `agent`, `langgraph`, `cli`, `hitl`, `ssh`, `audit`

## Dependency Constraints

`constraints.txt` is generated from the verified release environment and
committed with the release. Use it for reproducible installs:

```bash
pip install -c constraints.txt linuxagent
pip install -c constraints.txt -e ".[dev]"
```

Regenerate before a release after the full gate passes:

```bash
pip-compile pyproject.toml --extra dev --extra anthropic --extra pyinstaller --strip-extras --no-emit-trusted-host --index-url https://pypi.org/simple --output-file constraints.txt
```

## Artifact Provenance

Release artifacts are built by GitHub Actions from the tag commit. The release
workflow first verifies the wheel install path with `make verify-build`, then
uploads the same `dist/*.whl` and `dist/*.tar.gz` files to GitHub Release and
PyPI.

After publication, verify:

```bash
python -m pip install --upgrade linuxagent
linuxagent --version
linuxagent --help
```

If PyPI publication fails after GitHub Release creation, delete the GitHub
Release and tag, fix the release commit, and push a new tag for the corrected
version. If GitHub Release succeeds but PyPI already accepted the version, do
not overwrite artifacts; publish a new patch version and document the rollback
or superseded artifact in the release notes.

## Expected Artifacts

- `dist/*.whl`
- `dist/*.tar.gz`
- `coverage.xml` and `htmlcov/` from the CI coverage artifact

## Tag Release

```bash
python scripts/release_check.py --versions --tag v4.1.0
git tag -s v4.1.0 -m "v4.1.0"
git push origin v4.1.0
```

The GitHub Actions release workflow builds artifacts and creates a GitHub
Release using `docs/releases/<tag>.md` as the release body. The Chinese release
notes live in `docs/zh/releases/<tag>.md`. The same workflow publishes to PyPI
through Trusted Publishing.

## Release Checklist

- Version in `pyproject.toml` matches the tag.
- Version in `src/linuxagent/__init__.py` matches `pyproject.toml`.
- `CHANGELOG.md` and release notes mention user-visible changes.
- `constraints.txt` was refreshed or intentionally left unchanged.
- `make release-preflight` passes locally or in CI.
- GitHub Release contains wheel and sdist.
- PyPI page shows the new version.
- A fresh virtualenv can install and run `linuxagent --version`,
  `linuxagent --help`, and `linuxagent check`.
