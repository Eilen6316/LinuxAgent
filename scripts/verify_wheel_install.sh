#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WHEEL_PATH="${1:-}"
VERSION="$(python3 - <<'PY'
from pathlib import Path
import tomllib

print(tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
PY
)"
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
PIP_INDEX_URL="${LINUXAGENT_PIP_INDEX_URL:-https://pypi.org/simple}"
PIP_TIMEOUT="${LINUXAGENT_PIP_TIMEOUT:-60}"
python -m pip install --upgrade pip --index-url "$PIP_INDEX_URL" --timeout "$PIP_TIMEOUT" --retries 5
PIP_INSTALL=(python -m pip install --index-url "$PIP_INDEX_URL" --timeout "$PIP_TIMEOUT" --retries 5)
if [[ -f constraints.txt ]]; then
    PIP_INSTALL+=(--constraint constraints.txt)
fi
"${PIP_INSTALL[@]}" "$WHEEL_PATH"
if [[ "$(linuxagent --version)" != "linuxagent ${VERSION}" ]]; then
    echo "linuxagent --version does not match pyproject version ${VERSION}" >&2
    exit 1
fi
linuxagent --help >/dev/null
linuxagent check >/dev/null
python - <<'PY'
from importlib import resources
import yaml

import linuxagent.mcp_tools
import linuxagent.skills

root = resources.files("linuxagent")
required = [
    root / "_data" / "default.yaml",
    root / "_data" / "policy.default.yaml",
    root / "_data" / "prompts" / "system.md",
    root / "_data" / "prompts" / "analysis.md",
    root / "_data" / "prompts" / "direct_answer.md",
    root / "i18n" / "locales" / "zh-CN.yaml",
    root / "i18n" / "locales" / "en-US.yaml",
]
missing = [str(path) for path in required if not path.is_file()]
runbooks_dir = root / "_data" / "runbooks"
runbooks = sorted(path.name for path in runbooks_dir.iterdir() if path.name.endswith(".yaml"))
if missing:
    raise SystemExit(f"missing packaged data: {missing}")
if len(runbooks) != 11:
    raise SystemExit(f"expected 11 packaged runbooks, found {len(runbooks)}: {runbooks}")
config = yaml.safe_load((root / "_data" / "default.yaml").read_text(encoding="utf-8"))
if config.get("language") != "zh-CN":
    raise SystemExit(f"packaged default language is wrong: {config.get('language')}")
for section in ("sandbox", "file_patch", "cluster", "policy", "mcp", "skills"):
    if section not in config:
        raise SystemExit(f"missing packaged default config section: {section}")
sandbox = config["sandbox"]
if "tools" not in sandbox or "limits" not in sandbox:
    raise SystemExit("packaged sandbox config is missing tools or limits")
cluster = config["cluster"]
if "known_hosts_path" not in cluster:
    raise SystemExit("packaged cluster config is missing known_hosts_path")
mcp = config["mcp"]
if mcp.get("tools") != [
    "linuxagent.policy.classify",
    "linuxagent.audit.verify",
]:
    raise SystemExit(f"packaged mcp.tools is wrong: {mcp.get('tools')}")
if mcp.get("resources") != [
    "linuxagent://runbooks/summary",
    "linuxagent://skills/summary",
]:
    raise SystemExit(f"packaged mcp.resources is wrong: {mcp.get('resources')}")
skills = config["skills"]
if skills.get("enabled") is not False or skills.get("manifests") != []:
    raise SystemExit(f"packaged skills defaults are wrong: {skills}")
PY
