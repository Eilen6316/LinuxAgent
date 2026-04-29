"""Rich renderers for unified diffs."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

DEFAULT_MAX_LINES_PER_FILE = 200


@dataclass(frozen=True)
class DiffFile:
    old_path: str
    new_path: str
    lines: tuple[str, ...]

    @property
    def title(self) -> str:
        stats = self.stats
        suffix = f" (+{stats.additions} -{stats.deletions})"
        if self.new_path == "/dev/null":
            return f"{self.old_path}{suffix}"
        if self.old_path == "/dev/null":
            return f"{self.new_path}{suffix}"
        if self.old_path == self.new_path:
            return f"{self.new_path}{suffix}"
        return f"{self.old_path} -> {self.new_path}{suffix}"

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


def diff_summary(diff_text: str) -> str:
    files = parse_unified_diff_files(diff_text)
    if files:
        return DiffStats.from_files(files).summary
    stats = DiffStats.from_lines(tuple(diff_text.splitlines()))
    return stats.summary


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
