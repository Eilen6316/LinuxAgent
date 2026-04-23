#!/usr/bin/env bash
# bootstrap.sh — initialize a local LinuxAgent v4 dev environment.
# Creates a venv, installs dev extras, and seeds ./config.yaml (chmod 600).
#
# Usage:
#   ./scripts/bootstrap.sh           # default: ./.venv
#   VENV=myenv ./scripts/bootstrap.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-.venv}"

echo "==> Using ${PYTHON} -> $(${PYTHON} --version 2>&1)"
if [[ ! -d "$VENV" ]]; then
    echo "==> Creating virtualenv in ${VENV}"
    "$PYTHON" -m venv "$VENV"
fi

# shellcheck source=/dev/null
source "${VENV}/bin/activate"

echo "==> Upgrading pip"
python -m pip install --upgrade pip

echo "==> Installing linuxagent (editable) with dev extras"
pip install -e ".[dev]"

if [[ ! -f "./config.yaml" ]]; then
    echo "==> Seeding ./config.yaml from configs/example.yaml"
    cp configs/example.yaml ./config.yaml
    chmod 600 ./config.yaml
    echo "    Edit ./config.yaml and set api.api_key before running live."
else
    # Ensure existing file has correct permissions (idempotent).
    current_mode=$(stat -c '%a' ./config.yaml 2>/dev/null || stat -f '%Lp' ./config.yaml)
    if [[ "${current_mode}" != "600" ]]; then
        echo "==> ./config.yaml mode is ${current_mode}; fixing to 600"
        chmod 600 ./config.yaml
    fi
fi

echo "==> Installing pre-commit hooks (best-effort)"
pre-commit install || echo "    pre-commit install skipped (not critical)"

cat <<'EOF'

Done. Activate with:
  source .venv/bin/activate

Quick checks:
  linuxagent --help
  linuxagent check        # validate config loads
  make test
  make lint
EOF
