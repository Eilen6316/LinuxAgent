"""Policy command fact extraction and input validation."""

from __future__ import annotations

import posixpath
import re
import shlex
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from ..interfaces import CommandSource

MAX_COMMAND_LENGTH = 2048
_OPTION_TERMINATOR = "--"
_BIDI_CONTROLS: frozenset[str] = frozenset(
    {"LRE", "RLE", "LRO", "RLO", "LRI", "RLI", "FSI", "PDF", "PDI"}
)
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_WrapperUnwrapper = Callable[[tuple[str, ...]], tuple[tuple[str, ...], tuple[str, ...]] | None]


class PolicyInputError(ValueError):
    """Raised when command text fails structural validation."""


@dataclass(frozen=True)
class CommandFacts:
    command: str
    source: CommandSource
    tokens: tuple[str, ...] = ()
    effective_tokens: tuple[str, ...] = ()
    wrapper_prefix: tuple[str, ...] = ()
    parse_error: str | None = None
    input_error: str | None = None
    empty: bool = False

    @property
    def head(self) -> str | None:
        return self.tokens[0] if self.tokens else None

    @property
    def args(self) -> tuple[str, ...]:
        return self.tokens[1:]

    @property
    def effective_head(self) -> str | None:
        return self.effective_tokens[0] if self.effective_tokens else None

    @property
    def effective_args(self) -> tuple[str, ...]:
        return self.effective_tokens[1:]


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
    effective_tokens, wrapper_prefix = derive_effective(tokens)
    return CommandFacts(
        command=command,
        source=source,
        tokens=tokens,
        effective_tokens=effective_tokens,
        wrapper_prefix=wrapper_prefix,
        empty=not tokens,
    )


def derive_effective(
    tokens: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return normalized command tokens without mutating the original token stream."""
    prefix: list[str] = []
    current = tokens
    while current and _is_assignment(current[0]):
        prefix.append(current[0])
        current = current[1:]
    while current:
        unwrapped = _unwrap_wrapper_once(current)
        if unwrapped is None:
            break
        consumed, current = unwrapped
        if not consumed:
            break
        prefix.extend(consumed)
    return _normalize_effective_tokens(current), tuple(prefix)


def _unwrap_wrapper_once(
    tokens: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    handler = _WRAPPER_UNWRAPPERS.get(_command_name(tokens[0]))
    return None if handler is None else handler(tokens)


def _unwrap_env(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == _OPTION_TERMINATOR:
            index += 1
            break
        if token in {"-i", "--ignore-environment"} or token.startswith("--ignore-environment="):
            index += 1
            continue
        if token in {"-u", "--unset"}:
            if index + 1 >= len(tokens):
                return None
            index += 2
            continue
        if token.startswith("--unset=") or (token.startswith("-u") and len(token) > 2):
            index += 1
            continue
        if _is_assignment(token):
            index += 1
            continue
        if token.startswith("-"):
            return None
        break
    return _consumed_prefix(tokens, index)


def _unwrap_nice(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == _OPTION_TERMINATOR:
            index += 1
            break
        if token in {"-n", "--adjustment"}:
            if index + 1 >= len(tokens):
                return None
            index += 2
            continue
        if token.startswith("--adjustment=") or (token.startswith("-n") and len(token) > 2):
            index += 1
            continue
        break
    return _consumed_prefix(tokens, index)


def _unwrap_ionice(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == _OPTION_TERMINATOR:
            index += 1
            break
        if token in {"-c", "--class", "-n", "--classdata"}:
            if index + 1 >= len(tokens):
                return None
            index += 2
            continue
        if (
            token.startswith("--class=")
            or token.startswith("--classdata=")
            or (token.startswith("-c") and len(token) > 2)
            or (token.startswith("-n") and len(token) > 2)
        ):
            index += 1
            continue
        break
    return _consumed_prefix(tokens, index)


def _unwrap_timeout(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == _OPTION_TERMINATOR:
            index += 1
            break
        if token in {"-s", "--signal", "-k", "--kill-after"}:
            if index + 1 >= len(tokens):
                return None
            index += 2
            continue
        if token.startswith("--signal=") or token.startswith("--kill-after="):
            index += 1
            continue
        if token in {"--preserve-status", "--foreground", "-v", "--verbose"}:
            index += 1
            continue
        if token.startswith("-"):
            return None
        break
    if index >= len(tokens):
        return None
    index += 1
    return _consumed_prefix(tokens, index)


def _unwrap_no_arg_wrapper(
    tokens: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    index = 1
    if index < len(tokens) and tokens[index] == _OPTION_TERMINATOR:
        index += 1
    return _consumed_prefix(tokens, index)


def _unwrap_stdbuf(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == _OPTION_TERMINATOR:
            index += 1
            break
        width = _stdbuf_option_width(tokens, index)
        if width == 0:
            break
        index += width
    return _consumed_prefix(tokens, index)


def _stdbuf_option_width(tokens: tuple[str, ...], index: int) -> int:
    token = tokens[index]
    value_flags = ("--input", "--output", "--error")
    if token in value_flags:
        return 2 if index + 1 < len(tokens) else 0
    if any(token.startswith(f"{flag}=") for flag in value_flags):
        return 1
    if token in {"-i", "-o", "-e"}:
        return 2 if index + 1 < len(tokens) else 0
    if len(token) > 2 and token[:2] in {"-i", "-o", "-e"}:
        return 1
    return 0


_WRAPPER_UNWRAPPERS: dict[str, _WrapperUnwrapper] = {
    "env": _unwrap_env,
    "nice": _unwrap_nice,
    "ionice": _unwrap_ionice,
    "timeout": _unwrap_timeout,
    "nohup": _unwrap_no_arg_wrapper,
    "setsid": _unwrap_no_arg_wrapper,
    "time": _unwrap_no_arg_wrapper,
    "stdbuf": _unwrap_stdbuf,
}


def _consumed_prefix(
    tokens: tuple[str, ...],
    index: int,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    if index >= len(tokens):
        return None
    return tokens[:index], tokens[index:]


def _normalize_effective_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    if not tokens:
        return ()
    return (_command_name(tokens[0]), *tokens[1:])


def _command_name(token: str) -> str:
    return posixpath.basename(token) or token


def _is_assignment(token: str) -> bool:
    return bool(_ASSIGNMENT_RE.match(token))
