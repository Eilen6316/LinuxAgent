"""Policy engine implementation."""

from __future__ import annotations

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
        lolbin_decision = decision_from_lolbins(analyze_lolbins(facts.tokens, shell), source)
        child_decisions = _child_policy_decisions(shell, self, source=source, depth=depth)
        return merge_decisions(
            (lolbin_decision, shell_decision, local_decision, *child_decisions),
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
