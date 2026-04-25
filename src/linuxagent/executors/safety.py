"""Compatibility facade over the capability-based policy engine."""

from __future__ import annotations

import re

from ..interfaces import CommandSource, SafetyLevel, SafetyResult
from ..policy import DEFAULT_POLICY_ENGINE
from ..policy.builtin_rules import INTERACTIVE_COMMANDS
from ..policy.engine import MAX_COMMAND_LENGTH, PolicyInputError
from ..policy.engine import is_interactive_tokens as _policy_is_interactive
from ..policy.engine import validate_input as _policy_validate_input

DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "mkfs",
        "dd",
        "shred",
        "fdisk",
        "parted",
        "wipefs",
        "mkswap",
    }
)
DESTRUCTIVE_ARG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^-[rRfF]*[rRfF][rRfF]+[rRfF]*$"),
    re.compile(r"^--no-preserve-root$"),
    re.compile(r"^--force$"),
)
DESTRUCTIVE_SUBCOMMAND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("systemctl", re.compile(r"^(stop|disable|mask|kill|poweroff|reboot|halt|restart|reload|enable)$")),
    ("kubectl", re.compile(r"^(delete|drain|cordon|replace|apply|patch|scale|rollout)$")),
    ("docker", re.compile(r"^(rm|rmi|kill|prune|system|stop|restart|compose|volume|network)$")),
    ("git", re.compile(r"^(push|reset|clean|checkout|rebase)$")),
    ("helm", re.compile(r"^(uninstall|delete|rollback|upgrade|install)$")),
)


class InputValidationError(ValueError):
    """Raised when a command fails pre-tokenization input checks."""


def validate_input(command: str, *, max_length: int = MAX_COMMAND_LENGTH) -> None:
    """Reject structurally dangerous input before tokenization."""
    try:
        _policy_validate_input(command, max_length=max_length)
    except PolicyInputError as exc:
        raise InputValidationError(str(exc)) from exc


def is_interactive(tokens: list[str]) -> bool:
    """Return True when the first token names an interactive command."""
    return _policy_is_interactive(tokens)


def is_destructive(command: str) -> bool:
    """True when ``command`` can never be session-whitelisted."""
    decision = DEFAULT_POLICY_ENGINE.evaluate(command, source=CommandSource.USER)
    if decision.level is SafetyLevel.BLOCK:
        return True
    destructive_prefixes = (
        "filesystem.delete",
        "filesystem.truncate",
        "block_device.",
        "service.mutate",
        "package.remove",
        "container.mutate",
        "kubernetes.",
        "network.firewall",
        "identity.mutate",
        "cron.mutate",
        "privilege.sudo",
    )
    return any(capability.startswith(destructive_prefixes) for capability in decision.capabilities)


def is_safe(
    command: str,
    *,
    source: CommandSource = CommandSource.USER,
) -> SafetyResult:
    """Classify ``command`` into SAFE / CONFIRM / BLOCK."""
    decision = DEFAULT_POLICY_ENGINE.evaluate(command, source=source)
    return SafetyResult(
        level=decision.level,
        reason=decision.reason,
        matched_rule=decision.matched_rule,
        command_source=decision.command_source,
    )


__all__ = [
    "INTERACTIVE_COMMANDS",
    "MAX_COMMAND_LENGTH",
    "DESTRUCTIVE_ARG_PATTERNS",
    "DESTRUCTIVE_COMMANDS",
    "DESTRUCTIVE_SUBCOMMAND_PATTERNS",
    "InputValidationError",
    "is_destructive",
    "is_interactive",
    "is_safe",
    "validate_input",
]
