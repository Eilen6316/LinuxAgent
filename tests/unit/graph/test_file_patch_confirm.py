"""Focused tests for file-patch confirmation helpers."""

from __future__ import annotations

import json
from pathlib import Path

from linuxagent.config.models import FilePatchConfig
from linuxagent.graph.file_patch_confirm import _patch_payload, _selected_plan
from linuxagent.plans import evaluate_file_patch_plan, parse_file_patch_plan


def _two_file_plan(first: Path, second: Path):
    payload = {
        "plan_type": "file_patch",
        "goal": "create two files",
        "files_changed": [str(first), str(second)],
        "unified_diff": "\n".join(
            [
                "--- /dev/null",
                f"+++ {first}",
                "@@ -0,0 +1 @@",
                "+one",
                "--- /dev/null",
                f"+++ {second}",
                "@@ -0,0 +1 @@",
                "+two",
                "",
            ]
        ),
        "risk_summary": "Create two files.",
        "verification_commands": ["python -m py_compile app.py"],
        "expected_side_effects": ["filesystem.write"],
    }
    return parse_file_patch_plan(json.dumps(payload))


def test_patch_payload_preserves_confirmation_shape(tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    plan = _two_file_plan(first, second)
    safety = evaluate_file_patch_plan(plan, FilePatchConfig(allow_roots=(tmp_path,)))

    payload = _patch_payload(plan, "audit-1", safety, repair_attempt=1)

    assert payload["type"] == "confirm_file_patch"
    assert payload["audit_id"] == "audit-1"
    assert payload["files_changed"] == [str(first), str(second)]
    assert f"+++ {first}" in payload["unified_diff"]
    assert f"+++ {second}" in payload["unified_diff"]
    assert payload["risk_level"] == safety.risk_level
    assert payload["risk_reasons"] == list(safety.reasons)
    assert payload["repair_attempt"] == 1
    assert payload["verification_commands"] == ["python -m py_compile app.py"]
    assert payload["expected_side_effects"] == ["filesystem.write"]


def test_selected_plan_filters_files_from_interrupt_response(tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    plan = _two_file_plan(first, second)

    selected = _selected_plan(plan, {"selected_files": [str(second)]})

    assert selected.files_changed == (str(second),)
    assert f"+++ {first}" not in selected.unified_diff
    assert f"+++ {second}" in selected.unified_diff
