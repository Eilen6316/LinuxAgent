"""Rich renderers for unified diffs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

DEFAULT_MAX_LINES_PER_FILE = 200
_HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class DiffFile:
    old_path: str
    new_path: str
    lines: tuple[str, ...]

    @property
    def title(self) -> str:
        stats = self.stats
        return f"{self.action} {self.display_path} (+{stats.additions} -{stats.deletions})"

    @property
    def action(self) -> str:
        if self.old_path == "/dev/null":
            return "Created"
        if self.new_path == "/dev/null":
            return "Deleted"
        return "Edited"

    @property
    def display_path(self) -> str:
        if self.new_path == "/dev/null":
            return self.old_path
        if self.old_path == "/dev/null":
            return self.new_path
        if self.old_path == self.new_path:
            return self.new_path
        return f"{self.old_path} -> {self.new_path}"

    @property
    def stats(self) -> DiffStats:
        return DiffStats.from_lines(self.lines)


@dataclass(frozen=True)
class DiffStats:
    additions: int = 0
    deletions: int = 0
    files: int = 0

    @classmethod
    def from_lines(cls, lines: tuple[str, ...]) -> DiffStats:
        additions = sum(1 for line in lines if _is_addition(line))
        deletions = sum(1 for line in lines if _is_deletion(line))
        return cls(additions=additions, deletions=deletions, files=1)

    @classmethod
    def from_files(cls, files: tuple[DiffFile, ...]) -> DiffStats:
        stats = [file.stats for file in files]
        return cls(
            additions=sum(item.additions for item in stats),
            deletions=sum(item.deletions for item in stats),
            files=len(files),
        )

    @property
    def summary(self) -> str:
        file_label = "file" if self.files == 1 else "files"
        return f"{self.files} {file_label}, +{self.additions} -{self.deletions}"


class DiffRenderer:
    def __init__(self, *, max_lines_per_file: int | None = DEFAULT_MAX_LINES_PER_FILE) -> None:
        self._max_lines_per_file = max_lines_per_file

    def render(self, diff_text: str) -> RenderableType:
        files = parse_unified_diff_files(diff_text)
        if not files:
            return render_unified_diff(diff_text)
        total_files = len(files)
        panels = [
            Panel(
                self._render_file(file),
                title=f"[bold]{index}/{total_files} {file.title}[/]",
                subtitle=self._file_subtitle(file),
                border_style="bright_magenta",
                padding=(1, 2),
            )
            for index, file in enumerate(files, start=1)
        ]
        return Group(*panels)

    def _render_file(self, file: DiffFile) -> Text:
        lines = file.lines
        truncated = False
        if self._max_lines_per_file is not None and len(lines) > self._max_lines_per_file:
            lines = lines[: self._max_lines_per_file]
            truncated = True
        rendered = render_compact_file_diff(file, lines)
        if truncated:
            remaining = len(file.lines) - len(lines)
            rendered.append(
                f"... page 1/{_page_count(len(file.lines), len(lines))}; "
                f"{remaining} more diff lines hidden\n",
                style="dim",
            )
        return rendered

    def _file_subtitle(self, file: DiffFile) -> str:
        if self._max_lines_per_file is None or len(file.lines) <= self._max_lines_per_file:
            return ""
        pages = _page_count(len(file.lines), self._max_lines_per_file)
        return f"[dim]page 1/{pages}; showing first {self._max_lines_per_file} lines[/]"


def diff_summary(diff_text: str) -> str:
    files = parse_unified_diff_files(diff_text)
    if files:
        return DiffStats.from_files(files).summary
    stats = DiffStats.from_lines(tuple(diff_text.splitlines()))
    return stats.summary


def diff_display_summary(
    diff_text: str, *, max_lines_per_file: int | None = DEFAULT_MAX_LINES_PER_FILE
) -> str:
    files = parse_unified_diff_files(diff_text)
    if not files:
        line_count = len(diff_text.splitlines())
        if max_lines_per_file is None or line_count <= max_lines_per_file:
            return "full diff shown"
        return _hidden_summary(line_count, max_lines_per_file)
    hidden_files = tuple(file for file in files if _is_truncated(file, max_lines_per_file))
    if not hidden_files:
        return "full diff shown"
    hidden_lines = sum(len(file.lines) - int(max_lines_per_file or 0) for file in hidden_files)
    return f"{len(hidden_files)} file diff paged, {hidden_lines} lines hidden"


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


def render_compact_file_diff(file: DiffFile, lines: tuple[str, ...] | None = None) -> Text:
    rendered = Text()
    rendered.append(f"{file.title}\n", style="bold white")
    old_line = 0
    new_line = 0
    for line in lines or file.lines:
        hunk = _HUNK_RE.match(line)
        if hunk is not None:
            old_line = int(hunk.group("old"))
            new_line = int(hunk.group("new"))
            rendered.append("    ...\n", style="dim")
            continue
        old_line, new_line = _render_compact_line(rendered, line, old_line, new_line)
    return rendered


def _render_compact_line(
    rendered: Text, line: str, old_line: int, new_line: int
) -> tuple[int, int]:
    if line.startswith(("--- ", "+++ ")):
        return old_line, new_line
    if _is_deletion(line):
        rendered.append(f"{old_line:>5} -{line[1:]}\n", style="red")
        return old_line + 1, new_line
    if _is_addition(line):
        rendered.append(f"{new_line:>5} +{line[1:]}\n", style="green")
        return old_line, new_line + 1
    content = line[1:] if line.startswith(" ") else line
    rendered.append(f"{new_line:>5}  {content}\n", style="white")
    return old_line + 1, new_line + 1


def diff_line_style(line: str) -> str:
    if _is_addition(line):
        return "green"
    if _is_deletion(line):
        return "red"
    if line.startswith("@@"):
        return "yellow"
    return "white"


def _clean_diff_header(raw: str) -> str:
    path = raw.strip().split("\t", 1)[0]
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _is_addition(line: str) -> bool:
    return line.startswith("+") and not line.startswith("+++")


def _is_deletion(line: str) -> bool:
    return line.startswith("-") and not line.startswith("---")


def _is_truncated(file: DiffFile, max_lines_per_file: int | None) -> bool:
    return max_lines_per_file is not None and len(file.lines) > max_lines_per_file


def _page_count(total_lines: int, page_size: int) -> int:
    return max(1, (total_lines + page_size - 1) // page_size)


def _hidden_summary(line_count: int, max_lines_per_file: int) -> str:
    hidden = line_count - max_lines_per_file
    return f"diff paged, {hidden} lines hidden"
