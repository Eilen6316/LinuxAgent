#!/usr/bin/env python3
"""Enforce per-module coverage floors for security-critical modules.

The global ``--cov-fail-under`` gate averages over the whole package, so a
single security-critical module can collapse toward zero and still be hidden
behind a high overall percentage. This check reads a ``coverage.json`` report
and enforces explicit per-module floors on the code that forms the trust
boundary (policy, redaction, audit, file-patch safety, sandbox, execution),
so a regression in any one of them fails the gate loudly.

Floors are intentionally conservative starting points, set well below the
coverage these modules reach under the full Linux test suite, so the check
does not break on first run and can be ratcheted upward as coverage improves:

* ``_CORE_FLOOR`` applies to pure logic on the trust boundary.
* ``_RUNTIME_FLOOR`` applies to platform-runtime code (process/sandbox runners)
  whose full coverage is only measurable on Linux; kept lower until a Linux
  baseline exists.

Usage::

    coverage json -o coverage.json
    python scripts/check_coverage_floors.py coverage.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypeAlias

# Pure logic on the trust boundary. Measured well above this floor on the
# cross-platform test subset, and the full Linux suite only adds coverage.
_CORE_FLOOR = 70.0
# Platform-runtime code (process/sandbox runners). Their full coverage is only
# measurable on Linux (the runner tests need process groups / cgroups / bwrap),
# so this is a conservative catastrophic-collapse guard rather than a tight
# floor; the dedicated ``make sandbox`` CI job is the real gate for these.
_RUNTIME_FLOOR = 48.0

_CORE_MODULES: tuple[str, ...] = (
    "linuxagent/policy/engine.py",
    "linuxagent/policy/facts.py",
    "linuxagent/policy/decisions.py",
    "linuxagent/policy/shell_structure.py",
    "linuxagent/policy/lolbins.py",
    "linuxagent/policy/rule_matcher.py",
    "linuxagent/policy/argv_match.py",
    "linuxagent/policy/argv.py",
    "linuxagent/policy/capabilities.py",
    "linuxagent/policy/models.py",
    "linuxagent/policy/builtin_rules.py",
    "linuxagent/policy/config_rules.py",
    "linuxagent/policy/config_expansion.py",
    "linuxagent/policy/interactive.py",
    "linuxagent/policy/tool_grammar.py",
    "linuxagent/security/redaction.py",
    "linuxagent/security/output_guard.py",
    "linuxagent/security/stream_guard.py",
    "linuxagent/audit.py",
    "linuxagent/network_fetch.py",
    "linuxagent/network_policy.py",
    "linuxagent/plans/file_patch_safety.py",
    "linuxagent/plans/file_patch_transaction.py",
    "linuxagent/plans/file_patch_apply.py",
    "linuxagent/plans/file_patch_parser.py",
    "linuxagent/plans/file_patch_paths.py",
    "linuxagent/plans/file_patch_models.py",
    "linuxagent/plans/models.py",
    "linuxagent/executors/safety.py",
    "linuxagent/executors/session_whitelist.py",
    "linuxagent/sandbox/models.py",
    "linuxagent/sandbox/profiles.py",
)

_RUNTIME_MODULES: tuple[str, ...] = (
    "linuxagent/sandbox/local.py",
    "linuxagent/sandbox/bubblewrap.py",
    "linuxagent/sandbox/cgroup.py",
    "linuxagent/sandbox/seccomp.py",
    "linuxagent/sandbox/noop.py",
    "linuxagent/executors/linux_executor.py",
)

_CoverageMap: TypeAlias = dict[str, float]


def load_coverage(path: Path) -> _CoverageMap:
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files")
    if not isinstance(files, dict):
        raise SystemExit(f"{path}: coverage report has no 'files' mapping")
    coverage: _CoverageMap = {}
    for file_path, entry in files.items():
        summary = entry.get("summary", {}) if isinstance(entry, dict) else {}
        percent = summary.get("percent_covered")
        if isinstance(percent, int | float):
            coverage[file_path.replace("\\", "/")] = float(percent)
    return coverage


def _coverage_for(coverage: _CoverageMap, suffix: str) -> float | None:
    for file_path, percent in coverage.items():
        if file_path.endswith(suffix):
            return percent
    return None


def _check(
    modules: tuple[str, ...],
    floor: float,
    coverage: _CoverageMap,
    violations: list[str],
) -> int:
    checked = 0
    for suffix in modules:
        percent = _coverage_for(coverage, suffix)
        if percent is None:
            violations.append(f"{suffix}: no coverage data (was the module measured?)")
            continue
        checked += 1
        if percent < floor:
            violations.append(f"{suffix}: {percent:.1f}% < floor {floor:.0f}%")
    return checked


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_coverage_floors.py <coverage.json>", file=sys.stderr)
        return 2
    coverage = load_coverage(Path(argv[1]))
    violations: list[str] = []
    checked = _check(_CORE_MODULES, _CORE_FLOOR, coverage, violations)
    checked += _check(_RUNTIME_MODULES, _RUNTIME_FLOOR, coverage, violations)
    if violations:
        print("Per-module coverage floors failed:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print(f"Per-module coverage floors OK ({checked} security modules checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
