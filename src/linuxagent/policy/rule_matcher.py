"""Compiled policy rule matching."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

from ..interfaces import CommandSource
from .argv_match import CompiledArgvPattern
from .facts import CommandFacts
from .interactive import is_interactive_tokens
from .models import PolicyMatch, PolicyRule
from .tool_grammar import candidate_subcommands


class CompiledRule:
    def __init__(
        self,
        rule: PolicyRule,
        interactive_commands: frozenset[str],
        noninteractive_flags: tuple[str, ...],
        noninteractive_command_flags: dict[str, frozenset[str]],
    ) -> None:
        self.rule = rule
        self._interactive_commands = interactive_commands
        self._noninteractive_flags = noninteractive_flags
        self._noninteractive_command_flags = noninteractive_command_flags
        self._args_regex = tuple(re.compile(pattern) for pattern in rule.match.args_regex)
        self._args_all_regex = tuple(re.compile(pattern) for pattern in rule.match.args_all_regex)
        self._path_regex = tuple(re.compile(pattern) for pattern in rule.match.path_regex)
        self._embedded_regex = tuple(re.compile(pattern) for pattern in rule.match.embedded_regex)
        self._argv = tuple(CompiledArgvPattern(pattern) for pattern in rule.match.argv)

    def matches(self, facts: CommandFacts) -> bool:
        match = self.rule.match
        structural = _structural_match_state(facts, match)
        if structural is not None:
            return structural
        if self._matches_source_or_interactive(facts):
            return True
        if self._embedded_regex and any(
            pattern.search(facts.command) for pattern in self._embedded_regex
        ):
            return True
        if not self._matches_command_shape(facts):
            return False
        if match.command or self._argv:
            return True
        return _has_non_command_matcher(match)

    def _matches_source_or_interactive(self, facts: CommandFacts) -> bool:
        match = self.rule.match
        if match.llm_first_run:
            return facts.source is CommandSource.LLM
        return bool(
            match.interactive
            and (
                is_interactive_tokens(
                    facts.tokens,
                    interactive_commands=self._interactive_commands,
                    noninteractive_flags=self._noninteractive_flags,
                    noninteractive_command_flags=self._noninteractive_command_flags,
                )
                or is_interactive_tokens(
                    facts.effective_tokens,
                    interactive_commands=self._interactive_commands,
                    noninteractive_flags=self._noninteractive_flags,
                    noninteractive_command_flags=self._noninteractive_command_flags,
                )
            )
        )

    def _matches_command_shape(self, facts: CommandFacts) -> bool:
        match = self.rule.match
        if self._argv and not any(pattern.matches(facts.tokens) for pattern in self._argv):
            return False
        if match.command and facts.effective_head not in match.command:
            return False
        if match.subcommand_any and not any(
            arg in match.subcommand_any
            for arg in candidate_subcommands(facts.effective_head, facts.effective_args)
        ):
            return False
        if match.args_any and not any(arg in match.args_any for arg in facts.effective_args):
            return False
        if self._args_regex and not any(
            pattern.match(arg) for arg in facts.effective_args for pattern in self._args_regex
        ):
            return False
        if self._args_all_regex and not all(
            any(pattern.match(arg) for arg in facts.effective_args)
            for pattern in self._args_all_regex
        ):
            return False
        if match.path_any and not any(arg in match.path_any for arg in facts.effective_args):
            return False
        return not self._path_regex or any(
            pattern.match(path)
            for arg in facts.effective_args
            for path in path_match_candidates(arg)
            for pattern in self._path_regex
        )


def matched_rules(
    facts: CommandFacts, compiled_rules: tuple[CompiledRule, ...]
) -> list[PolicyRule]:
    return [compiled.rule for compiled in compiled_rules if compiled.matches(facts)]


def _structural_match_state(facts: CommandFacts, match: PolicyMatch) -> bool | None:
    if match.input_validation:
        return facts.input_error is not None
    if facts.input_error is not None:
        return False
    if match.parse_error:
        return facts.parse_error is not None
    if facts.parse_error is not None:
        return False
    if match.empty:
        return facts.empty
    if facts.empty:
        return False
    return None


def _has_non_command_matcher(match: PolicyMatch) -> bool:
    return bool(
        match.argv
        or match.args_any
        or match.args_regex
        or match.args_all_regex
        or match.path_any
        or match.path_regex
        or match.subcommand_any
    )


def path_match_candidates(arg: str) -> tuple[str, ...]:
    candidates = [arg]
    expanded = _expand_user_path(arg)
    if expanded != arg:
        candidates.append(expanded)
    for value in tuple(candidates):
        normalized = _normalize_absolute_path(value)
        if normalized is not None and normalized not in candidates:
            candidates.append(normalized)
    return tuple(candidates)


def _expand_user_path(arg: str) -> str:
    if arg == "~" or arg.startswith("~/"):
        return str(Path(arg).expanduser())
    return arg


def _normalize_absolute_path(arg: str) -> str | None:
    if not arg.startswith("/"):
        return None
    return posixpath.normpath(arg)
