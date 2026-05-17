"""Focused tests for file-patch application helpers."""

from __future__ import annotations

from pathlib import Path

from linuxagent.config.models import FilePatchConfig
from linuxagent.graph.file_patch_apply import _apply_patch_result
from linuxagent.plans import file_patch_plan_json, parse_file_patch_plan


def test_apply_patch_result_records_success_audit_metadata(tmp_path: Path) -> None:
    target = tmp_path / "hello.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "#!/bin/sh\necho hi\n"))

    outcome = _apply_patch_result(plan, FilePatchConfig(allow_roots=(tmp_path,)), duration=0.5)

    assert outcome.result.exit_code == 0
    assert outcome.result.duration == 0.5
    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho hi\n"
    assert outcome.audit_metadata is not None
    assert outcome.audit_metadata["files_changed"] == [str(target)]
    assert outcome.audit_metadata["sandbox_root"] == str(tmp_path)
    assert outcome.audit_metadata["rollback_outcome"] == "not_needed"
    assert outcome.audit_metadata["backups"][0]["target"] == str(target)


def test_apply_patch_result_reports_failure_without_mutating_file(tmp_path: Path) -> None:
    target = tmp_path / "hello.sh"
    target.write_text("existing\n", encoding="utf-8")
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "#!/bin/sh\necho hi\n"))

    outcome = _apply_patch_result(plan, FilePatchConfig(allow_roots=(tmp_path,)), duration=0.25)

    assert outcome.result.exit_code == 1
    assert outcome.result.duration == 0.25
    assert "target already exists" in outcome.result.stderr
    assert target.read_text(encoding="utf-8") == "existing\n"
    assert outcome.audit_metadata is not None
    assert outcome.audit_metadata["files_changed"] == [str(target)]
    assert "sandbox_root" not in outcome.audit_metadata
