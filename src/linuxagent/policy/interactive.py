"""Interactive command detection for policy evaluation."""

from __future__ import annotations

from collections.abc import Iterable

from .builtin_rules import builtin_policy_config
from .models import CommandFlagSet

_SSH_OPTIONS_WITH_ARG: frozenset[str] = frozenset(
    {
        "-b",
        "-c",
        "-E",
        "-e",
        "-F",
        "-I",
        "-i",
        "-J",
        "-L",
        "-l",
        "-m",
        "-O",
        "-o",
        "-p",
        "-Q",
        "-R",
        "-S",
        "-W",
        "-w",
    }
)
_SSH_FORCE_TTY_FLAGS: frozenset[str] = frozenset({"-t", "-tt"})


def is_interactive_tokens(
    tokens: list[str] | tuple[str, ...],
    *,
    interactive_commands: frozenset[str] | None = None,
    noninteractive_flags: tuple[str, ...] | None = None,
    noninteractive_command_flags: dict[str, frozenset[str]] | None = None,
) -> bool:
    if (
        interactive_commands is None
        or noninteractive_flags is None
        or noninteractive_command_flags is None
    ):
        config = builtin_policy_config()
        interactive_commands = frozenset(config.interactive_commands)
        noninteractive_flags = config.noninteractive_flags
        noninteractive_command_flags = command_flag_map(config.noninteractive_command_flags)
    if not tokens or tokens[0] not in interactive_commands:
        return False
    if tokens[0] == "ssh":
        return _is_interactive_ssh(tokens)
    if _has_command_noninteractive_flag(tokens, noninteractive_command_flags):
        return False
    return not has_noninteractive_flag(tokens, noninteractive_flags)


def command_flag_map(command_flags: Iterable[CommandFlagSet]) -> dict[str, frozenset[str]]:
    return {item.command: frozenset(item.flags) for item in command_flags}


def has_noninteractive_flag(tokens: list[str] | tuple[str, ...], flags: tuple[str, ...]) -> bool:
    return any(
        token == flag or token.startswith(f"{flag}=") for token in tokens[1:] for flag in flags
    )


def _has_command_noninteractive_flag(
    tokens: list[str] | tuple[str, ...],
    command_flags: dict[str, frozenset[str]],
) -> bool:
    flags = command_flags.get(tokens[0])
    if flags is None:
        return False
    return any(_command_flag_matches(token, flags) for token in tokens[1:])


def _command_flag_matches(token: str, flags: frozenset[str]) -> bool:
    return any(
        token == flag
        or token.startswith(flag)
        and len(token) > len(flag)
        or _short_flag_is_bundled(token, flag)
        for flag in flags
    )


def _short_flag_is_bundled(token: str, flag: str) -> bool:
    return (
        len(flag) == 2 and flag.startswith("-") and token.startswith("-") and flag[1] in token[1:]
    )


def _is_interactive_ssh(tokens: list[str] | tuple[str, ...]) -> bool:
    if _ssh_forces_tty(tokens):
        return True
    destination_index = _ssh_destination_index(tokens)
    if destination_index is None:
        return True
    return len(tokens) == destination_index + 1


def _ssh_forces_tty(tokens: list[str] | tuple[str, ...]) -> bool:
    return any(token in _SSH_FORCE_TTY_FLAGS for token in tokens[1:])


def _ssh_destination_index(tokens: list[str] | tuple[str, ...]) -> int | None:
    index = 1
    while index < len(tokens):
        arg = tokens[index]
        if arg == "--":
            return index + 1 if index + 1 < len(tokens) else None
        if not arg.startswith("-") or arg == "-":
            return index
        index += 2 if _ssh_option_takes_separate_arg(arg, index, tokens) else 1
    return None


def _ssh_option_takes_separate_arg(
    arg: str,
    index: int,
    tokens: list[str] | tuple[str, ...],
) -> bool:
    return arg in _SSH_OPTIONS_WITH_ARG and index + 1 < len(tokens)
