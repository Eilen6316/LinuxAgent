"""FilePatchPlan parsing and application tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linuxagent.config.models import FilePatchConfig
from linuxagent.plans import (
    FilePatchApplyError,
    apply_file_patch_plan,
    apply_unified_diff,
    evaluate_file_patch_plan,
    file_patch_plan_json,
    parse_file_patch_plan,
    select_file_patch_plan_files,
    summarize_file_patch_plan,
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


def test_create_diff_rejects_existing_file_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "hello.sh"
    path.write_text("existing\n", encoding="utf-8")
    plan = parse_file_patch_plan(file_patch_plan_json(str(path), "#!/bin/sh\necho hi\n"))

    with pytest.raises(FilePatchApplyError, match="target already exists"):
        apply_unified_diff(plan.unified_diff)

    assert path.read_text(encoding="utf-8") == "existing\n"


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


def test_apply_unified_diff_relocates_hunk_when_line_number_is_stale(tmp_path: Path) -> None:
    path = tmp_path / "disk_info.sh"
    path.write_text(
        "\n".join(
            [
                'echo -e "\\n[11] 磁盘空间占用最大的目录"',
                'du -sh /* 2>/dev/null | sort -rh | head -10 || echo "权限不足无法扫描"',
                'echo -e "\\n完成"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    diff = "\n".join(
        [
            f"--- {path}",
            f"+++ {path}",
            "@@ -2,2 +2,4 @@",
            ' echo -e "\\n[11] 磁盘空间占用最大的目录"',
            ' du -sh /* 2>/dev/null | sort -rh | head -10 || echo "权限不足无法扫描"',
            '+echo -e "\\n[12] CPU 信息"',
            "+lscpu",
            "",
        ]
    )

    apply_unified_diff(diff)

    content = path.read_text(encoding="utf-8")
    assert 'echo -e "\\n[12] CPU 信息"' in content
    assert "lscpu" in content


def test_apply_unified_diff_rejects_paths_outside_allow_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    target = tmp_path / "outside" / "blocked.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "#!/bin/sh\n"))
    config = FilePatchConfig(allow_roots=(allowed,), high_risk_roots=())

    with pytest.raises(FilePatchApplyError, match="allow_roots"):
        apply_file_patch_plan(plan, config)

    assert not target.exists()


def test_apply_unified_diff_rejects_relative_path_traversal(tmp_path: Path) -> None:
    diff = "\n".join(["--- /dev/null", "+++ ../outside.txt", "@@ -0,0 +1 @@", "+blocked", ""])
    config = FilePatchConfig(allow_roots=(tmp_path / "workspace",))

    with pytest.raises(FilePatchApplyError, match="allow_roots"):
        apply_unified_diff(diff, config=config, cwd=tmp_path / "workspace")

    assert not (tmp_path / "outside.txt").exists()


def test_evaluate_file_patch_plan_marks_allowed_high_risk_path(tmp_path: Path) -> None:
    target = tmp_path / "etc" / "demo.conf"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "enabled=true\n"))
    config = FilePatchConfig(allow_roots=(tmp_path,), high_risk_roots=(tmp_path / "etc",))

    report = evaluate_file_patch_plan(plan, config)

    assert report.allowed is True
    assert report.risk_level == "high"
    assert report.high_risk_paths == (target,)


def test_evaluate_file_patch_plan_blocks_path_before_reading_target(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret-from-outside\n", encoding="utf-8")
    diff = "\n".join(
        [
            f"--- {outside}",
            f"+++ {outside}",
            "@@ -1,1 +1,1 @@",
            "-wrong-context",
            "+replacement",
            "",
        ]
    )
    plan = parse_file_patch_plan(
        json.dumps(
            {
                "plan_type": "file_patch",
                "goal": "edit outside file",
                "files_changed": [str(outside)],
                "unified_diff": diff,
            }
        )
    )

    report = evaluate_file_patch_plan(plan, FilePatchConfig(allow_roots=(allowed,)))

    assert report.allowed is False
    assert any("allow_roots" in reason for reason in report.reasons)
    assert not any("secret-from-outside" in reason for reason in report.reasons)
    assert not any("wrong-context" in reason for reason in report.reasons)


def test_evaluate_file_patch_plan_marks_large_rewrite_high_risk(tmp_path: Path) -> None:
    target = tmp_path / "disk_info.sh"
    original = [f"echo old-{index}" for index in range(1, 21)]
    target.write_text("\n".join(original) + "\n", encoding="utf-8")
    diff_lines = [f"--- {target}", f"+++ {target}", "@@ -1,20 +1,20 @@"]
    for index in range(1, 13):
        diff_lines.append(f"-echo old-{index}")
        diff_lines.append(f"+echo new-{index}")
    diff_lines.extend(f" {line}" for line in original[12:])
    plan = parse_file_patch_plan(
        json.dumps(
            {
                "plan_type": "file_patch",
                "goal": "rewrite script",
                "files_changed": [str(target)],
                "unified_diff": "\n".join(diff_lines) + "\n",
            }
        )
    )

    report = evaluate_file_patch_plan(plan, FilePatchConfig(allow_roots=(tmp_path,)))

    assert report.allowed is True
    assert report.risk_level == "high"
    assert any("large rewrite of existing file" in reason for reason in report.reasons)


def test_evaluate_file_patch_plan_blocks_create_intent_update_diff(tmp_path: Path) -> None:
    target = tmp_path / "disk_info.sh"
    target.write_text("#!/bin/sh\necho old\n", encoding="utf-8")
    plan = parse_file_patch_plan(
        json.dumps(
            {
                "plan_type": "file_patch",
                "goal": "create disk script",
                "files_changed": [str(target)],
                "unified_diff": "\n".join(
                    [
                        f"--- {target}",
                        f"+++ {target}",
                        "@@ -1,2 +1,3 @@",
                        " #!/bin/sh",
                        " echo old",
                        "+echo disk",
                        "",
                    ]
                ),
            }
        )
    )

    report = evaluate_file_patch_plan(
        plan, FilePatchConfig(allow_roots=(tmp_path,)), request_intent="create"
    )

    assert report.allowed is False
    assert "create request attempted to update existing file" in report.reasons[0]


def test_apply_file_patch_plan_applies_permission_changes(tmp_path: Path) -> None:
    target = tmp_path / "hello.sh"
    payload = json.loads(file_patch_plan_json(str(target), "#!/bin/sh\necho hi\n"))
    payload["permission_changes"] = [
        {"path": str(target), "mode": "0755", "reason": "make script executable"}
    ]
    plan = parse_file_patch_plan(json.dumps(payload))

    result = apply_file_patch_plan(plan, FilePatchConfig(allow_roots=(tmp_path,)))

    assert result.permissions_changed == (target,)
    assert target.stat().st_mode & 0o777 == 0o755


def test_select_file_patch_plan_files_applies_only_selected_file(tmp_path: Path) -> None:
    first = tmp_path / "one.sh"
    second = tmp_path / "two.sh"
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
        "permission_changes": [{"path": str(second), "mode": "0755"}],
    }
    plan = parse_file_patch_plan(json.dumps(payload))

    selected = select_file_patch_plan_files(plan, (str(second),))
    result = apply_file_patch_plan(selected, FilePatchConfig(allow_roots=(tmp_path,)))

    assert selected.files_changed == (str(second),)
    assert result.files_changed == (second,)
    assert result.permissions_changed == (second,)
    assert not first.exists()
    assert second.read_text(encoding="utf-8") == "two\n"
    assert second.stat().st_mode & 0o777 == 0o755


def test_select_file_patch_plan_files_rejects_unknown_selection(tmp_path: Path) -> None:
    target = tmp_path / "one.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "one\n"))

    with pytest.raises(FilePatchApplyError, match="selected file"):
        select_file_patch_plan_files(plan, (str(tmp_path / "missing.sh"),))


def test_summarize_file_patch_plan_labels_each_changed_file(tmp_path: Path) -> None:
    target = tmp_path / "demo.sh"
    plan = parse_file_patch_plan(file_patch_plan_json(str(target), "#!/bin/sh\necho hi\n"))

    summaries = summarize_file_patch_plan(plan)

    assert [summary.label for summary in summaries] == [f"Created {target} (+2 -0)"]


def test_permission_changes_disabled_block_before_writing(tmp_path: Path) -> None:
    target = tmp_path / "hello.sh"
    payload = json.loads(file_patch_plan_json(str(target), "#!/bin/sh\necho hi\n"))
    payload["permission_changes"] = [{"path": str(target), "mode": "0755"}]
    plan = parse_file_patch_plan(json.dumps(payload))
    config = FilePatchConfig(allow_roots=(tmp_path,), allow_permission_changes=False)

    with pytest.raises(FilePatchApplyError, match="permission changes are disabled"):
        apply_file_patch_plan(plan, config)

    assert not target.exists()


def test_missing_permission_target_blocks_before_writing(tmp_path: Path) -> None:
    target = tmp_path / "hello.sh"
    missing = tmp_path / "missing.sh"
    payload = json.loads(file_patch_plan_json(str(target), "#!/bin/sh\necho hi\n"))
    payload["permission_changes"] = [{"path": str(missing), "mode": "0755"}]
    plan = parse_file_patch_plan(json.dumps(payload))

    with pytest.raises(FilePatchApplyError, match="permission target does not exist"):
        apply_file_patch_plan(plan, FilePatchConfig(allow_roots=(tmp_path,)))

    assert not target.exists()


def test_file_patch_plan_rejects_invalid_permission_mode(tmp_path: Path) -> None:
    target = tmp_path / "hello.sh"
    payload = json.loads(file_patch_plan_json(str(target), "#!/bin/sh\n"))
    payload["permission_changes"] = [{"path": str(target), "mode": "bad"}]

    with pytest.raises(ValueError, match="mode"):
        parse_file_patch_plan(json.dumps(payload))


def test_apply_unified_diff_reports_failed_file_hunk_and_lines(tmp_path: Path) -> None:
    path = tmp_path / "config.txt"
    path.write_text("actual=true\n", encoding="utf-8")
    diff = "\n".join([f"--- {path}", f"+++ {path}", "@@ -1,1 +1,1 @@", "-old=true", "+new=true"])

    with pytest.raises(FilePatchApplyError) as exc_info:
        apply_unified_diff(diff)

    message = str(exc_info.value)
    assert f"file={path}" in message
    assert "hunk=1" in message
    assert "expected='old=true'" in message
    assert "actual='actual=true'" in message


def test_parse_file_patch_plan_rejects_command_plan_shape() -> None:
    with pytest.raises(ValueError, match="FilePatchPlan"):
        parse_file_patch_plan(json.dumps({"goal": "missing diff", "commands": []}))
