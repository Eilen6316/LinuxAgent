"""Diff renderer tests."""

from __future__ import annotations

from rich.console import Console

from linuxagent.ui.diff_renderer import (
    DiffRenderer,
    diff_display_summary,
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

    assert [file.title for file in files] == [
        "Edited one.py (+1 -1)",
        "Created two.py (+1 -0)",
    ]


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
    assert "Edited one.py (+1 -1)" in rendered
    assert "Created two.py (+1 -0)" in rendered
    assert "1 -old" in rendered
    assert "1 +created" in rendered


def test_diff_renderer_can_truncate_large_file_diff() -> None:
    console = Console(record=True, width=120)
    renderer = DiffRenderer(max_lines_per_file=3)

    console.print(renderer.render("--- demo.py\n+++ demo.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"))
    rendered = console.export_text()

    assert "more diff lines hidden" in rendered
    assert "page 1/2" in rendered


def test_diff_renderer_labels_file_panels_with_indexes() -> None:
    console = Console(record=True, width=120)
    renderer = DiffRenderer()

    console.print(
        renderer.render(
            "\n".join(
                [
                    "--- one.py",
                    "+++ one.py",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                    "--- two.py",
                    "+++ two.py",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                ]
            )
        )
    )

    rendered = console.export_text()
    assert "1/2 Edited one.py (+1 -1)" in rendered
    assert "2/2 Edited two.py (+1 -1)" in rendered


def test_diff_renderer_truncates_large_diff_by_default() -> None:
    console = Console(record=True, width=120)
    body = "\n".join(f"+line {index}" for index in range(250))
    renderer = DiffRenderer()

    console.print(renderer.render(f"--- /dev/null\n+++ demo.py\n@@ -0,0 +250 @@\n{body}\n"))

    assert "more diff lines hidden" in console.export_text()


def test_diff_renderer_can_render_later_pages() -> None:
    console = Console(record=True, width=120)
    body = "\n".join(f"+line {index}" for index in range(5))
    renderer = DiffRenderer(max_lines_per_file=4)
    file = parse_unified_diff_files(f"--- /dev/null\n+++ demo.py\n@@ -0,0 +5 @@\n{body}\n")[0]

    console.print(renderer.render_file_page(file, 2))

    rendered = console.export_text()
    assert "page 2/2" in rendered
    assert "+line 0" not in rendered
    assert "+line 4" in rendered


def test_diff_display_summary_reports_hidden_lines() -> None:
    body = "\n".join(f"+line {index}" for index in range(5))
    summary = diff_display_summary(
        f"--- /dev/null\n+++ demo.py\n@@ -0,0 +5 @@\n{body}\n",
        max_lines_per_file=3,
    )

    assert summary == "1 file diff paged, 5 lines hidden"


def test_diff_line_style_marks_changed_lines_only() -> None:
    assert diff_line_style("+new") == "green"
    assert diff_line_style("-old") == "red"
    assert diff_line_style("@@ -1 +1 @@") == "yellow"
    assert diff_line_style("+++ b/file.py") == "white"
    assert diff_line_style("--- a/file.py") == "white"
