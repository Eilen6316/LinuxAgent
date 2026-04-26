#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WHEEL_PATH="${1:-}"
if [[ -z "$WHEEL_PATH" ]]; then
    WHEEL_PATH="$(python3 - <<'PY'
from pathlib import Path
import tomllib

version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
matches = sorted(Path("dist").glob(f"linuxagent-{version}-*.whl"))
if matches:
    print(matches[0])
PY
)"
fi

if [[ -z "$WHEEL_PATH" || ! -f "$WHEEL_PATH" ]]; then
    echo "wheel artifact not found" >&2
    exit 1
fi

TMP_VENV="$(mktemp -d)"
trap 'rm -rf "$TMP_VENV"' EXIT
python3 -m venv "$TMP_VENV"
source "$TMP_VENV/bin/activate"
PIP_INSTALL=(pip install --index-url "${LINUXAGENT_PIP_INDEX_URL:-https://pypi.org/simple}")
if [[ -f constraints.txt ]]; then
    PIP_INSTALL+=(--constraint constraints.txt)
fi
"${PIP_INSTALL[@]}" "$WHEEL_PATH"
linuxagent --help >/dev/null
python - <<'PY'
from importlib import resources

root = resources.files("linuxagent")
required = [
    root / "_data" / "default.yaml",
    root / "_data" / "policy.default.yaml",
    root / "_data" / "prompts" / "system.md",
    root / "_data" / "prompts" / "analysis.md",
    root / "_data" / "prompts" / "direct_answer.md",
]
missing = [str(path) for path in required if not path.is_file()]
runbooks_dir = root / "_data" / "runbooks"
runbooks = sorted(path.name for path in runbooks_dir.iterdir() if path.name.endswith(".yaml"))
if missing:
    raise SystemExit(f"missing packaged data: {missing}")
if len(runbooks) != 11:
    raise SystemExit(f"expected 11 packaged runbooks, found {len(runbooks)}: {runbooks}")
PY
