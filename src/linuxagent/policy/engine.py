"""Policy engine implementation."""

from __future__ import annotations

import shlex

from ..interfaces import CommandSource, SafetyLevel
from .decisions import (
    decision_from_lolbins,
    decision_from_matches,
    decision_from_shell_structure,
    merge_decisions,
)
from .facts import (
    MAX_COMMAND_LENGTH,
    CommandFacts,
    PolicyInputError,
    command_facts,
    validate_input,
)
from .interactive import command_flag_map, is_interactive_tokens
from .lolbins import analyze_lolbins
from .models import PolicyConfig, PolicyDecision
from .rule_matcher import CompiledRule, matched_rules
from .shell_structure import ShellStructure, analyze_shell_structure

__all__ = [
    "MAX_COMMAND_LENGTH",
    "PolicyEngine",
    "PolicyInputError",
    "is_interactive_tokens",
    "validate_input",
]

_MAX_SHELL_STRUCTURE_DEPTH = 4
_OPTION_TERMINATOR = "--"


class PolicyEngine:
    def __init__(self, config: PolicyConfig) -> None:
        self._config = config
        self._interactive_commands = frozenset(config.interactive_commands)
        self._noninteractive_flags = tuple(config.noninteractive_flags)
        self._noninteractive_command_flags = command_flag_map(config.noninteractive_command_flags)
        self._compiled = tuple(
            CompiledRule(
                rule,
                self._interactive_commands,
                self._noninteractive_flags,
                self._noninteractive_command_flags,
            )
            for rule in config.rules
        )

    @property
    def config(self) -> PolicyConfig:
        return self._config

    def evaluate(
        self,
        command: str,
        *,
        source: CommandSource = CommandSource.USER,
    ) -> PolicyDecision:
        return self._evaluate(command, source=source, depth=0)

    def _evaluate(
        self,
        command: str,
        *,
        source: CommandSource,
        depth: int,
    ) -> PolicyDecision:
        facts = command_facts(command, source=source)
        local_decision = _decision_from_facts(facts, self._compiled, source)
        if facts.input_error is not None or facts.parse_error is not None:
            return local_decision
        shell = analyze_shell_structure(command)
        shell_decision = decision_from_shell_structure(shell, source)
        lolbin_decision = decision_from_lolbins(
            analyze_lolbins(facts.effective_tokens, shell), source
        )
        wrapper_decisions = _wrapper_policy_decisions(facts, self, source=source, depth=depth)
        sudo_decision = _sudo_policy_decision(facts, self, source=source, depth=depth)
        child_decisions = _child_policy_decisions(shell, self, source=source, depth=depth)
        return merge_decisions(
            (
                lolbin_decision,
                shell_decision,
                local_decision,
                *wrapper_decisions,
                *(() if sudo_decision is None else (sudo_decision,)),
                *child_decisions,
            ),
            source,
        )


def _decision_from_facts(
    facts: CommandFacts,
    compiled_rules: tuple[CompiledRule, ...],
    source: CommandSource,
) -> PolicyDecision:
    matches = matched_rules(facts, compiled_rules)
    if not matches:
        return PolicyDecision(level=SafetyLevel.SAFE, command_source=source)
    return decision_from_matches(matches, source)


def _child_policy_decisions(
    shell: ShellStructure,
    engine: PolicyEngine,
    *,
    source: CommandSource,
    depth: int,
) -> tuple[PolicyDecision, ...]:
    if depth >= _MAX_SHELL_STRUCTURE_DEPTH:
        return ()
    return tuple(
        engine._evaluate(child, source=source, depth=depth + 1) for child in shell.child_commands
    )


def _wrapper_policy_decisions(
    facts: CommandFacts,
    engine: PolicyEngine,
    *,
    source: CommandSource,
    depth: int,
) -> tuple[PolicyDecision, ...]:
    if depth >= _MAX_SHELL_STRUCTURE_DEPTH or not facts.wrapper_prefix:
        return ()
    return (engine._evaluate(shlex.join(facts.wrapper_prefix), source=source, depth=depth + 1),)


def _sudo_policy_decision(
    facts: CommandFacts,
    engine: PolicyEngine,
    *,
    source: CommandSource,
    depth: int,
) -> PolicyDecision | None:
    if depth >= _MAX_SHELL_STRUCTURE_DEPTH:
        return None
    inner = _sudo_inner_command(facts.effective_tokens)
    if inner is None:
        return None
    return engine._evaluate(inner, source=source, depth=depth + 1)


def _sudo_inner_command(tokens: tuple[str, ...]) -> str | None:
    if not tokens or tokens[0] != "sudo":
        return None
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == _OPTION_TERMINATOR:
            index += 1
            break
        if token in _SUDO_OPTIONS_WITH_VALUES:
            if index + 1 >= len(tokens):
                return None
            index += 2
            continue
        if _sudo_option_has_inline_value(token):
            index += 1
            continue
        if token.startswith("--"):
            index += 1
            continue
        if _sudo_short_option_token(token):
            index += 1
            continue
        break
    if index >= len(tokens):
        return None
    return shlex.join(tokens[index:])


_SUDO_OPTIONS_WITH_VALUES: frozenset[str] = frozenset(
    {
        "-u",
        "--user",
        "-g",
        "--group",
        "-h",
        "--host",
        "-p",
        "--prompt",
        "-C",
        "--close-from",
        "-T",
        "--command-timeout",
        "-D",
        "--chdir",
        "-R",
        "--chroot",
        "-r",
        "--role",
        "-t",
        "--type",
        "-U",
        "--other-user",
    }
)
_SUDO_LONG_OPTIONS_WITH_VALUES: frozenset[str] = frozenset(
    option for option in _SUDO_OPTIONS_WITH_VALUES if option.startswith("--")
)
_SUDO_SHORT_OPTIONS_WITH_VALUES: frozenset[str] = frozenset(
    option
    for option in _SUDO_OPTIONS_WITH_VALUES
    if option.startswith("-") and not option.startswith("--")
)
_SUDO_SHORT_OPTIONS_WITHOUT_VALUES = frozenset("AbEHikKlnPSsvV")


def _sudo_option_has_inline_value(token: str) -> bool:
    if any(token.startswith(f"{option}=") for option in _SUDO_LONG_OPTIONS_WITH_VALUES):
        return True
    return any(
        token.startswith(option) and len(token) > len(option)
        for option in _SUDO_SHORT_OPTIONS_WITH_VALUES
    )


def _sudo_short_option_token(token: str) -> bool:
    if len(token) < 2 or not token.startswith("-") or token.startswith("--"):
        return False
    return all(char in _SUDO_SHORT_OPTIONS_WITHOUT_VALUES for char in token[1:])
