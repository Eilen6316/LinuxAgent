"""Focused tests for file-patch repair helpers."""

from __future__ import annotations

from pathlib import Path

from linuxagent.config.models import FilePatchConfig
from linuxagent.graph.file_patch_repair import _parse_repair_candidate, should_repair_file_patch
from linuxagent.interfaces import ExecutionResult
from linuxagent.plans import FilePatchPlan, file_patch_plan_json, parse_file_patch_plan


def test_parse_repair_candidate_accepts_embedded_json(tmp_path: Path) -> None:
    target = tmp_path / "fixed.sh"
    payload = file_patch_plan_json(str(target), "#!/bin/sh\necho fixed\n")

    parsed = _parse_repair_candidate(f"Here is the corrected patch:\n```json\n{payload}\n```")

    assert isinstance(parsed, FilePatchPlan)
    assert parsed.files_changed == (str(target),)


def test_should_repair_file_patch_stops_after_configured_attempts(tmp_path: Path) -> None:
    target = tmp_path / "fixed.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "#!/bin/sh\necho fixed\n"))

    assert not should_repair_file_patch(
        {
            "file_patch_plan": plan,
            "execution_result": ExecutionResult(
                "apply file patch",
                1,
                "",
                "target already exists",
                0.1,
            ),
            "file_patch_repair_attempts": 1,
            "file_patch_max_repair_attempts": 1,
        }
    )


def test_should_repair_file_patch_defaults_to_configured_budget(tmp_path: Path) -> None:
    target = tmp_path / "fixed.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "#!/bin/sh\necho fixed\n"))

    assert should_repair_file_patch(
        {
            "file_patch_plan": plan,
            "execution_result": ExecutionResult(
                "apply file patch",
                1,
                "",
                "target already exists",
                0.1,
            ),
        }
    )


def test_should_repair_file_patch_honors_zero_attempt_budget(tmp_path: Path) -> None:
    target = tmp_path / "fixed.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "#!/bin/sh\necho fixed\n"))
    config = FilePatchConfig(max_repair_attempts=0)

    assert not should_repair_file_patch(
        {
            "file_patch_plan": plan,
            "execution_result": ExecutionResult(
                "apply file patch",
                1,
                "",
                "target already exists",
                0.1,
            ),
            "file_patch_max_repair_attempts": config.max_repair_attempts,
        }
    )
