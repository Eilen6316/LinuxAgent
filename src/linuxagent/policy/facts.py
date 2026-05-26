"""Policy command fact extraction and input validation."""

from __future__ import annotations

import shlex
import unicodedata
from dataclasses import dataclass

from ..interfaces import CommandSource

MAX_COMMAND_LENGTH = 2048
_BIDI_CONTROLS: frozenset[str] = frozenset(
    {"LRE", "RLE", "LRO", "RLO", "LRI", "RLI", "FSI", "PDF", "PDI"}
)


class PolicyInputError(ValueError):
    """Raised when command text fails structural validation."""


@dataclass(frozen=True)
class CommandFacts:
    command: str
    source: CommandSource
    tokens: tuple[str, ...] = ()
    parse_error: str | None = None
    input_error: str | None = None
    empty: bool = False

    @property
    def head(self) -> str | None:
        return self.tokens[0] if self.tokens else None

    @property
    def args(self) -> tuple[str, ...]:
        return self.tokens[1:]


def validate_input(command: str, *, max_length: int = MAX_COMMAND_LENGTH) -> None:
    if len(command) > max_length:
        raise PolicyInputError(f"command exceeds max length ({max_length})")
    if "\x00" in command:
        raise PolicyInputError("command contains NUL byte")
    for ch in command:
        if unicodedata.bidirectional(ch) in _BIDI_CONTROLS:
            raise PolicyInputError(
                f"command contains bidirectional control character U+{ord(ch):04X}"
            )


def command_facts(command: str, *, source: CommandSource) -> CommandFacts:
    try:
        validate_input(command)
    except PolicyInputError as exc:
        return CommandFacts(command=command, source=source, input_error=str(exc))
    try:
        tokens = tuple(shlex.split(command))
    except ValueError as exc:
        return CommandFacts(
            command=command, source=source, parse_error=f"shell parse failed: {exc}"
        )
    return CommandFacts(command=command, source=source, tokens=tokens, empty=not tokens)
