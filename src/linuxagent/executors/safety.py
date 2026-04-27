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
    command
    for rule in DEFAULT_POLICY_ENGINE.config.rules
    if rule.never_whitelist
    for command in rule.match.command
)
DESTRUCTIVE_ARG_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for rule in DEFAULT_POLICY_ENGINE.config.rules
    if rule.never_whitelist
    for pattern in rule.match.args_regex
)
DESTRUCTIVE_SUBCOMMAND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (command, re.compile(f"^({'|'.join(map(re.escape, rule.match.subcommand_any))})$"))
    for rule in DEFAULT_POLICY_ENGINE.config.rules
    if rule.never_whitelist and rule.match.subcommand_any
    for command in rule.match.command
)
_NEVER_WHITELIST_RULES: frozenset[str] = frozenset(
    rule.legacy_rule for rule in DEFAULT_POLICY_ENGINE.config.rules if rule.never_whitelist
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
    return any(rule in _NEVER_WHITELIST_RULES for rule in decision.matched_rules)


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
        risk_score=decision.risk_score,
        capabilities=decision.capabilities,
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
