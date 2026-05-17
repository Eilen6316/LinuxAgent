"""Regression tests for hardcoded runtime string auditing."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.i18n_audit import scan_chinese_strings, scan_english_candidates

_SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "linuxagent"


def test_no_untracked_chinese_strings_in_runtime_source() -> None:
    findings = scan_chinese_strings(_SOURCE_ROOT)

    assert findings == []


def test_english_phrase_inventory_is_report_only() -> None:
    findings = scan_english_candidates(_SOURCE_ROOT)

    assert any("English phrase candidate" in finding.render() for finding in findings)
    assert any(finding.path.as_posix().endswith("tools/catalog.py") for finding in findings)


def test_chinese_audit_detects_untracked_source_string(tmp_path: Path) -> None:
    source = tmp_path / "src"
    package = source / "linuxagent"
    package.mkdir(parents=True)
    target = package / "demo.py"
    target.write_text('message = "未登记中文"\n', encoding="utf-8")

    findings = scan_chinese_strings(source)

    assert len(findings) == 1
    assert findings[0].line == 1
    assert "未登记中文" in findings[0].text


def test_chinese_audit_ignores_comments(tmp_path: Path) -> None:
    source = tmp_path / "src"
    package = source / "linuxagent"
    package.mkdir(parents=True)
    target = package / "demo.py"
    target.write_text('# 中文注释不属于运行时字符串\nmessage = "ok"\n', encoding="utf-8")

    assert ast.parse(target.read_text(encoding="utf-8"))
    assert scan_chinese_strings(source) == []
