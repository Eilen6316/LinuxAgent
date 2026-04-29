"""Diff renderer tests."""

from __future__ import annotations

from rich.console import Console

from linuxagent.ui.diff_renderer import (
    DiffRenderer,
    diff_line_style,
    diff_summary,
    parse_unified_diff_files,
)


def test_parse_unified_diff_files_splits_multiple_files() -> None:
    files = parse_unified_diff_files(
        "\n".join(
            [
                "--- a/one.py",
                "+++ b/one.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
                "--- /dev/null",
                "+++ two.py",
                "@@ -0,0 +1 @@",
                "+created",
            ]
        )
    )

    assert [file.title for file in files] == ["one.py (+1 -1)", "two.py (+1 -0)"]


def test_diff_summary_counts_files_additions_and_deletions() -> None:
    summary = diff_summary(
        "\n".join(
            [
                "--- a/one.py",
                "+++ b/one.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
                "--- /dev/null",
                "+++ two.py",
                "@@ -0,0 +1 @@",
                "+created",
            ]
        )
    )

    assert summary == "2 files, +2 -1"


def test_diff_renderer_outputs_file_scoped_panels() -> None:
    console = Console(record=True, width=120)
    renderer = DiffRenderer()

    console.print(
        renderer.render(
            "\n".join(
                [
                    "--- a/one.py",
                    "+++ b/one.py",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                    "--- /dev/null",
                    "+++ two.py",
                    "@@ -0,0 +1 @@",
                    "+created",
                ]
            )
        )
    )

    rendered = console.export_text()
    assert "one.py" in rendered
    assert "two.py" in rendered
    assert "-old" in rendered
    assert "+created" in rendered


def test_diff_renderer_can_truncate_large_file_diff() -> None:
    console = Console(record=True, width=120)
    renderer = DiffRenderer(max_lines_per_file=3)

    console.print(renderer.render("--- demo.py\n+++ demo.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"))

    assert "more diff lines hidden" in console.export_text()


def test_diff_renderer_truncates_large_diff_by_default() -> None:
    console = Console(record=True, width=120)
    body = "\n".join(f"+line {index}" for index in range(250))
    renderer = DiffRenderer()

    console.print(renderer.render(f"--- /dev/null\n+++ demo.py\n@@ -0,0 +250 @@\n{body}\n"))

    assert "more diff lines hidden" in console.export_text()


def test_diff_line_style_marks_changed_lines_only() -> None:
    assert diff_line_style("+new") == "green"
    assert diff_line_style("-old") == "red"
    assert diff_line_style("@@ -1 +1 @@") == "yellow"
    assert diff_line_style("+++ b/file.py") == "white"
    assert diff_line_style("--- a/file.py") == "white"
