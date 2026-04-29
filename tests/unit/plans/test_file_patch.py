"""FilePatchPlan parsing and application tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linuxagent.plans import (
    FilePatchApplyError,
    apply_unified_diff,
    file_patch_plan_json,
    parse_file_patch_plan,
)


def test_parse_file_patch_plan_accepts_json_object(tmp_path: Path) -> None:
    path = tmp_path / "hello.sh"

    plan = parse_file_patch_plan(file_patch_plan_json(str(path), "#!/bin/sh\necho hi\n"))

    assert plan.plan_type == "file_patch"
    assert plan.files_changed == (str(path),)
    assert "+echo hi" in plan.unified_diff


def test_apply_unified_diff_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "hello.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(path), "#!/bin/sh\necho hi\n"))

    result = apply_unified_diff(plan.unified_diff)

    assert result.files_changed == (path,)
    assert path.read_text(encoding="utf-8") == "#!/bin/sh\necho hi\n"


def test_apply_unified_diff_updates_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.txt"
    path.write_text("old=true\nkeep=yes\n", encoding="utf-8")
    diff = "\n".join(
        [
            f"--- {path}",
            f"+++ {path}",
            "@@ -1,2 +1,2 @@",
            "-old=true",
            "+old=false",
            " keep=yes",
            "",
        ]
    )

    apply_unified_diff(diff)

    assert path.read_text(encoding="utf-8") == "old=false\nkeep=yes\n"


def test_apply_unified_diff_rejects_context_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "config.txt"
    path.write_text("actual=true\n", encoding="utf-8")
    diff = "\n".join([f"--- {path}", f"+++ {path}", "@@ -1,1 +1,1 @@", "-old=true", "+new=true"])

    with pytest.raises(FilePatchApplyError, match="context"):
        apply_unified_diff(diff)


def test_parse_file_patch_plan_rejects_command_plan_shape() -> None:
    with pytest.raises(ValueError, match="FilePatchPlan"):
        parse_file_patch_plan(json.dumps({"goal": "missing diff", "commands": []}))
