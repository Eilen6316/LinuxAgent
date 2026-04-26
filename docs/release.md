# Release

## Local Checklist

Run these before tagging:

```bash
make test
make lint
make type
make security
python -m tests.harness.runner --scenarios tests/harness/scenarios
python -m build --no-isolation
./scripts/verify_wheel_install.sh
```

The wheel verification step installs the built wheel in a temporary virtualenv,
checks `linuxagent --help`, and verifies packaged config, prompt, and runbook
data are present.

## Expected Artifacts

- `dist/*.whl`
- `dist/*.tar.gz`

## Tag Release

```bash
git tag v4.0.0
git push origin v4.0.0
```

The GitHub Actions release workflow then builds artifacts and creates a GitHub Release.
