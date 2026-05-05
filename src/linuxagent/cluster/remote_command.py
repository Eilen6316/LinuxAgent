"""Remote command admission for SSH execution.

Paramiko ``exec_command`` sends a string to the remote user's shell. This
module rejects shell-only syntax before any network connection is attempted so
remote execution is intentionally narrower than local argv-based execution.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

_FORBIDDEN_CHARS: frozenset[str] = frozenset("\n\r;&|<>(){}$`\\")
_FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {
        "&&",
        "||",
        "|",
        ";",
        "&",
        "<",
        ">",
        ">>",
        "<<",
    }
)
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "$(",
    "${",
    "`",
    "&&",
    "||",
    ">|",
    "<<",
    ">>",
)


class RemoteCommandError(ValueError):
    """Raised when a command is unsafe to send through a remote shell."""


@dataclass(frozen=True)
class RemoteCommand:
    raw: str
    argv: tuple[str, ...]


def validate_remote_command(command: str) -> RemoteCommand:
    """Return parsed argv if ``command`` is safe for SSH shell transport."""
    if not command.strip():
        raise RemoteCommandError("remote command is empty")
    try:
        argv = tuple(shlex.split(command))
    except ValueError as exc:
        raise RemoteCommandError(f"remote command shell parse failed: {exc}") from exc
    if not argv:
        raise RemoteCommandError("remote command is empty")
    _reject_shell_syntax(command, argv)
    return RemoteCommand(raw=command, argv=argv)


def _reject_shell_syntax(command: str, argv: tuple[str, ...]) -> None:
    for marker in _FORBIDDEN_SUBSTRINGS:
        if marker in command:
            raise RemoteCommandError(f"remote shell syntax is not allowed: {marker}")
    for token in argv:
        if token in _FORBIDDEN_TOKENS:
            raise RemoteCommandError(f"remote shell operator is not allowed: {token}")
        for char in token:
            if char in _FORBIDDEN_CHARS:
                raise RemoteCommandError(f"remote shell metacharacter is not allowed: {char}")
