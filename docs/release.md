# Release

## Local Checklist

Run these before tagging:

```bash
make test
make lint
make type
make security
python -m tests.harness.runner --scenarios tests/harness/scenarios
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

## Expected Artifacts

- `dist/*.whl`
- `dist/*.tar.gz`

## Tag Release

```bash
git tag v4.0.0
git push origin v4.0.0
```

The GitHub Actions release workflow then builds artifacts and creates a GitHub Release.
