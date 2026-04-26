# Contributing

Thanks for considering a contribution to LinuxAgent. The project is security
sensitive because it can execute local and remote Linux commands, so changes are
reviewed with a bias toward explicit behavior, tests, and conservative defaults.

## Start Here

1. Read [README.md](README.md), [docs/development.md](docs/development.md), and
   [docs/threat-model.md](docs/threat-model.md).
2. Create a virtualenv and install development dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

3. Run the local gate before opening a PR:

```bash
make lint
make type
make test
make security
make harness
make verify-build
```

Optional but recommended when your environment supports it:

```bash
make integration
make optional-anthropic
```

## Security Rules

- Never add `shell=True`.
- Never use substring checks such as `pattern in command` for command safety.
- Never reintroduce `paramiko.AutoAddPolicy`.
- Never bypass Human-in-the-Loop for LLM-generated or destructive commands.
- Never log secrets or send unredacted command output to an LLM path.

If your change touches command classification, HITL, SSH, audit, configuration,
or redaction, include focused tests that exercise the real logic rather than
mocking the security decision.

## Dependency Rules

Runtime dependencies live in `pyproject.toml`. `constraints.txt` is generated
for reproducible installs and release verification; do not hand-edit dependency
versions in multiple places without explaining why in the PR.

## Pull Request Expectations

- Keep the change scoped and explain the operator-visible behavior.
- Add or update tests for every public function or workflow you change.
- Update docs when behavior, configuration, release process, or security
  semantics change.
- Include migration notes for breaking changes.
- Do not commit local files such as `.work/`, `.codex/`, `config.yaml`, build
  output, caches, or secrets.

## Commit Messages

Use concise commit messages that describe the change, for example:

```text
fix: guard system tool outputs
docs: add production readiness checklist
```

Avoid internal planning labels in public commit messages.
