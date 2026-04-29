"""Rich renderers for unified diffs."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text


@dataclass(frozen=True)
class DiffFile:
    old_path: str
    new_path: str
    lines: tuple[str, ...]

    @property
    def title(self) -> str:
        if self.new_path == "/dev/null":
            return self.old_path
        if self.old_path == "/dev/null":
            return self.new_path
        if self.old_path == self.new_path:
            return self.new_path
        return f"{self.old_path} -> {self.new_path}"


class DiffRenderer:
    def __init__(self, *, max_lines_per_file: int | None = None) -> None:
        self._max_lines_per_file = max_lines_per_file

    def render(self, diff_text: str) -> RenderableType:
        files = parse_unified_diff_files(diff_text)
        if not files:
            return render_unified_diff(diff_text)
        panels = [
            Panel(
                self._render_file(file),
                title=f"[bold]{file.title}[/]",
                border_style="bright_magenta",
                padding=(1, 2),
            )
            for file in files
        ]
        return Group(*panels)

    def _render_file(self, file: DiffFile) -> Text:
        lines = file.lines
        truncated = False
        if self._max_lines_per_file is not None and len(lines) > self._max_lines_per_file:
            lines = lines[: self._max_lines_per_file]
            truncated = True
        rendered = render_unified_diff("\n".join(lines))
        if truncated:
            remaining = len(file.lines) - len(lines)
            rendered.append(f"... {remaining} more diff lines hidden\n", style="dim")
        return rendered


def parse_unified_diff_files(diff_text: str) -> tuple[DiffFile, ...]:
    lines = diff_text.splitlines()
    files: list[DiffFile] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_path = _clean_diff_header(lines[index][4:])
        start = index
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            continue
        new_path = _clean_diff_header(lines[index][4:])
        index += 1
        while index < len(lines) and not lines[index].startswith("--- "):
            index += 1
        files.append(
            DiffFile(old_path=old_path, new_path=new_path, lines=tuple(lines[start:index]))
        )
    return tuple(files)


def render_unified_diff(diff_text: str) -> Text:
    rendered = Text()
    for line in diff_text.splitlines():
        rendered.append(line, style=diff_line_style(line))
        rendered.append("\n")
    return rendered


def diff_line_style(line: str) -> str:
    if line.startswith("+") and not line.startswith("+++"):
        return "green"
    if line.startswith("-") and not line.startswith("---"):
        return "red"
    if line.startswith("@@"):
        return "yellow"
    return "white"


def _clean_diff_header(raw: str) -> str:
    path = raw.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path
