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
python3 -m venv --system-site-packages "$TMP_VENV"
source "$TMP_VENV/bin/activate"
pip install --no-deps "$WHEEL_PATH"
linuxagent --help >/dev/null
