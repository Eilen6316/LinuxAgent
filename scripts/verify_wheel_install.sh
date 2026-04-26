#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WHEEL_PATH="${1:-}"
if [[ -z "$WHEEL_PATH" ]]; then
    WHEEL_PATH="$(find dist -maxdepth 1 -name '*.whl' | head -n 1)"
fi

if [[ -z "$WHEEL_PATH" || ! -f "$WHEEL_PATH" ]]; then
    echo "wheel artifact not found" >&2
    exit 1
fi

TMP_VENV="$(mktemp -d)"
trap 'rm -rf "$TMP_VENV"' EXIT
python3 -m venv --system-site-packages "$TMP_VENV"
source "$TMP_VENV/bin/activate"
pip install --no-deps "$WHEEL_PATH"
linuxagent --help >/dev/null
python - <<'PY'
from importlib import resources

root = resources.files("linuxagent")
required = [
    root / "_data" / "default.yaml",
    root / "_data" / "policy.default.yaml",
    root / "_data" / "prompts" / "system.md",
]
missing = [str(path) for path in required if not path.is_file()]
runbooks_dir = root / "_data" / "runbooks"
runbooks = sorted(path.name for path in runbooks_dir.iterdir() if path.name.endswith(".yaml"))
if missing:
    raise SystemExit(f"missing packaged data: {missing}")
if len(runbooks) != 8:
    raise SystemExit(f"expected 8 packaged runbooks, found {len(runbooks)}: {runbooks}")
PY
