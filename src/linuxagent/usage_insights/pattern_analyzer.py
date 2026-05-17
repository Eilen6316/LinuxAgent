"""Command pattern analyzer."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ..executors import is_destructive, is_interactive


@dataclass(frozen=True)
class PatternAnalysis:
    command: str
    executable: str
    arg_count: int
    is_destructive: bool
    is_interactive: bool


class PatternAnalyzer:
    def analyze(self, command: str) -> PatternAnalysis:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        return PatternAnalysis(
            command=command,
            executable=tokens[0] if tokens else "",
            arg_count=max(len(tokens) - 1, 0),
            is_destructive=is_destructive(command),
            is_interactive=is_interactive(tokens),
        )
