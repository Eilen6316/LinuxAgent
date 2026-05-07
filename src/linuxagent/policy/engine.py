"""Policy engine implementation."""

from __future__ import annotations

import posixpath
import re
import shlex
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..interfaces import CommandSource, SafetyLevel
from .builtin_rules import builtin_policy_config
from .lolbins import LolbinFinding, analyze_lolbins
from .models import (
    ApprovalMode,
    PolicyApproval,
    PolicyConfig,
    PolicyDecision,
    PolicyMatch,
    PolicyRule,
)
from .shell_structure import ShellRedirect, ShellStructure, analyze_shell_structure

MAX_COMMAND_LENGTH = 2048
_BIDI_CONTROLS: frozenset[str] = frozenset(
    {"LRE", "RLE", "LRO", "RLO", "LRI", "RLI", "FSI", "PDF", "PDI"}
)
_MAX_SHELL_STRUCTURE_DEPTH = 4
_SENSITIVE_REDIRECT_PATHS: tuple[str, ...] = (
    r"^/etc(/|$)",
    r"^/root(/|$)",
    r"^/boot(/|$)",
    r"^/dev/[sh]d[a-z]",
    r"^/dev/nvme\d",
    r"^/home/[^/]+/\.ssh(/|$)",
)
_LEVEL_RANK = {SafetyLevel.SAFE: 0, SafetyLevel.CONFIRM: 1, SafetyLevel.BLOCK: 2}
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


class PolicyEngine:
    def __init__(self, config: PolicyConfig) -> None:
        self._config = config
        self._interactive_commands = frozenset(config.interactive_commands)
        self._noninteractive_flags = tuple(config.noninteractive_flags)
        self._compiled = tuple(
            _CompiledRule(rule, self._interactive_commands, self._noninteractive_flags)
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
        shell_decision = _decision_from_shell_structure(shell, source)
        lolbin_decision = _decision_from_lolbins(analyze_lolbins(facts.tokens, shell), source)
        child_decisions = _child_policy_decisions(shell, self, source=source, depth=depth)
        return _merge_decisions(
            (lolbin_decision, shell_decision, local_decision, *child_decisions),
            source,
        )


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


def is_interactive_tokens(
    tokens: list[str] | tuple[str, ...],
    *,
    interactive_commands: frozenset[str] | None = None,
    noninteractive_flags: tuple[str, ...] | None = None,
) -> bool:
    if interactive_commands is None or noninteractive_flags is None:
        config = builtin_policy_config()
        interactive_commands = frozenset(config.interactive_commands)
        noninteractive_flags = config.noninteractive_flags
    if not tokens or tokens[0] not in interactive_commands:
        return False
    if tokens[0] == "ssh":
        return _is_interactive_ssh(tokens)
    return not _has_noninteractive_flag(tokens, noninteractive_flags)


def _has_noninteractive_flag(tokens: list[str] | tuple[str, ...], flags: tuple[str, ...]) -> bool:
    return any(
        token == flag or token.startswith(f"{flag}=") for token in tokens[1:] for flag in flags
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


def _decision_from_matches(matches: list[PolicyRule], source: CommandSource) -> PolicyDecision:
    max_level = _max_level(rule.level for rule in matches)
    risk_score = max(rule.risk_score for rule in matches)
    capabilities = tuple(dict.fromkeys(cap for rule in matches for cap in rule.capabilities))
    matched_rules = tuple(dict.fromkeys(rule.legacy_rule for rule in matches))
    reason = _reason(matches[0], matches)
    return PolicyDecision(
        level=max_level,
        risk_score=risk_score,
        capabilities=capabilities,
        matched_rules=matched_rules,
        reason=reason,
        approval=_approval_for(max_level, matched_rules),
        command_source=source,
        can_whitelist=not any(rule.never_whitelist for rule in matches),
    )


def _decision_from_facts(
    facts: CommandFacts,
    compiled_rules: tuple[_CompiledRule, ...],
    source: CommandSource,
) -> PolicyDecision:
    matches = [compiled.rule for compiled in compiled_rules if compiled.matches(facts)]
    if not matches:
        return PolicyDecision(level=SafetyLevel.SAFE, command_source=source)
    return _decision_from_matches(matches, source)


def _decision_from_shell_structure(
    shell: ShellStructure,
    source: CommandSource,
) -> PolicyDecision:
    parse_decision = _shell_parse_decision(shell, source)
    if parse_decision is not None:
        return parse_decision
    redirect_decision = _redirect_decision(shell.redirects, source)
    if redirect_decision is not None:
        return redirect_decision
    if shell.control_operators:
        return _structural_decision(
            SafetyLevel.CONFIRM,
            65,
            ("shell.control",),
            ("SHELL_CONTROL",),
            "shell control operator requires review",
            source,
        )
    return PolicyDecision(level=SafetyLevel.SAFE, command_source=source)


def _shell_parse_decision(
    shell: ShellStructure,
    source: CommandSource,
) -> PolicyDecision | None:
    if shell.parse_error is None:
        return None
    return _structural_decision(
        SafetyLevel.BLOCK,
        100,
        ("shell.parse",),
        ("PARSE_ERROR",),
        shell.parse_error,
        source,
    )


def _redirect_decision(
    redirects: tuple[ShellRedirect, ...],
    source: CommandSource,
) -> PolicyDecision | None:
    write_targets = tuple(redirect.target for redirect in redirects if redirect.is_write)
    if not write_targets:
        return None
    if any(target and _is_sensitive_redirect_target(target) for target in write_targets):
        return _structural_decision(
            SafetyLevel.BLOCK,
            100,
            ("filesystem.sensitive_write",),
            ("SENSITIVE_REDIRECT",),
            "redirect targets sensitive path",
            source,
        )
    return _structural_decision(
        SafetyLevel.CONFIRM,
        60,
        ("filesystem.write",),
        ("REDIRECT_WRITE",),
        "shell redirect writes output",
        source,
    )


def _structural_decision(
    level: SafetyLevel,
    risk_score: int,
    capabilities: tuple[str, ...],
    matched_rules: tuple[str, ...],
    reason: str,
    source: CommandSource,
) -> PolicyDecision:
    return PolicyDecision(
        level=level,
        risk_score=risk_score,
        capabilities=capabilities,
        matched_rules=matched_rules,
        reason=reason,
        approval=_approval_for(level, matched_rules),
        command_source=source,
        can_whitelist=level is not SafetyLevel.BLOCK,
    )


def _decision_from_lolbins(
    findings: tuple[LolbinFinding, ...],
    source: CommandSource,
) -> PolicyDecision:
    if not findings:
        return PolicyDecision(level=SafetyLevel.SAFE, command_source=source)
    max_level = _max_level(finding.level for finding in findings)
    matched_rules = tuple(dict.fromkeys(finding.matched_rule for finding in findings))
    return PolicyDecision(
        level=max_level,
        risk_score=max(finding.risk_score for finding in findings),
        capabilities=tuple(dict.fromkeys(finding.capability for finding in findings)),
        matched_rules=matched_rules,
        reason="; ".join(dict.fromkeys(finding.reason for finding in findings)),
        approval=_approval_for(max_level, matched_rules),
        command_source=source,
        can_whitelist=False,
    )


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


def _is_sensitive_redirect_target(target: str) -> bool:
    return any(
        re.match(pattern, candidate)
        for candidate in _path_match_candidates(target)
        for pattern in _SENSITIVE_REDIRECT_PATHS
    )


def _merge_decisions(
    decisions: Iterable[PolicyDecision],
    source: CommandSource,
) -> PolicyDecision:
    materialized = tuple(decisions)
    max_level = _max_level(decision.level for decision in materialized)
    ordered = _highest_risk_first(materialized)
    matched_rules = _merged_matched_rules(ordered)
    if not matched_rules:
        return PolicyDecision(level=max_level, command_source=source)
    return PolicyDecision(
        level=max_level,
        risk_score=max(decision.risk_score for decision in materialized),
        capabilities=_merged_capabilities(ordered),
        matched_rules=matched_rules,
        reason=_merged_reason(ordered),
        approval=_approval_for(max_level, matched_rules),
        command_source=source,
        can_whitelist=all(decision.can_whitelist for decision in materialized),
    )


def _highest_risk_first(decisions: tuple[PolicyDecision, ...]) -> tuple[PolicyDecision, ...]:
    indexed = tuple(enumerate(decisions))
    ordered = sorted(
        indexed,
        key=lambda item: (
            _LEVEL_RANK[item[1].level],
            _source_priority(item[0], item[1]),
            item[1].risk_score,
            -item[0],
        ),
        reverse=True,
    )
    return tuple(decision for _, decision in ordered)


def _source_priority(index: int, decision: PolicyDecision) -> int:
    if decision.level is SafetyLevel.BLOCK:
        return 0
    return 1 if index >= 2 else 0


def _merged_matched_rules(decisions: tuple[PolicyDecision, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(rule for decision in decisions for rule in decision.matched_rules))


def _merged_capabilities(decisions: tuple[PolicyDecision, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(cap for decision in decisions for cap in decision.capabilities))


def _merged_reason(decisions: tuple[PolicyDecision, ...]) -> str | None:
    reasons = tuple(dict.fromkeys(decision.reason for decision in decisions if decision.reason))
    return "; ".join(reasons) if reasons else None


def _max_level(levels: Iterable[SafetyLevel]) -> SafetyLevel:
    return max(levels, key=lambda level: _LEVEL_RANK[level])


def _approval_for(level: SafetyLevel, matched_rules: tuple[str, ...]) -> PolicyApproval:
    if level is SafetyLevel.CONFIRM:
        mode = (
            ApprovalMode.BATCH_OPERATOR
            if "BATCH_CONFIRM" in matched_rules
            else ApprovalMode.SINGLE_OPERATOR
        )
        return PolicyApproval(required=True, mode=mode)
    return PolicyApproval()


def _reason(first: PolicyRule, matches: list[PolicyRule]) -> str:
    if first.legacy_rule == "INPUT_VALIDATION":
        return "command failed structural validation"
    if first.legacy_rule == "PARSE_ERROR":
        return "shell parse failed"
    if first.legacy_rule == "EMPTY":
        return "empty command"
    if first.legacy_rule == "EMBEDDED_DANGER":
        return first.reason
    if len(matches) == 1:
        return first.reason
    return "; ".join(rule.reason for rule in matches[:3])


class _CompiledRule:
    def __init__(
        self,
        rule: PolicyRule,
        interactive_commands: frozenset[str],
        noninteractive_flags: tuple[str, ...],
    ) -> None:
        self.rule = rule
        self._interactive_commands = interactive_commands
        self._noninteractive_flags = noninteractive_flags
        self._args_regex = tuple(re.compile(pattern) for pattern in rule.match.args_regex)
        self._path_regex = tuple(re.compile(pattern) for pattern in rule.match.path_regex)
        self._embedded_regex = tuple(re.compile(pattern) for pattern in rule.match.embedded_regex)

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
        if match.command:
            return True
        return _has_non_command_matcher(match)

    def _matches_source_or_interactive(self, facts: CommandFacts) -> bool:
        match = self.rule.match
        if match.llm_first_run:
            return facts.source is CommandSource.LLM
        return bool(
            match.interactive
            and is_interactive_tokens(
                facts.tokens,
                interactive_commands=self._interactive_commands,
                noninteractive_flags=self._noninteractive_flags,
            )
        )

    def _matches_command_shape(self, facts: CommandFacts) -> bool:
        match = self.rule.match
        if match.command and facts.head not in match.command:
            return False
        if match.subcommand_any and (not facts.args or facts.args[0] not in match.subcommand_any):
            return False
        if match.args_any and not any(arg in match.args_any for arg in facts.args):
            return False
        if self._args_regex and not any(
            pattern.match(arg) for arg in facts.args for pattern in self._args_regex
        ):
            return False
        if match.path_any and not any(arg in match.path_any for arg in facts.args):
            return False
        if self._path_regex and not any(
            pattern.match(path)
            for arg in facts.args
            for path in _path_match_candidates(arg)
            for pattern in self._path_regex
        ):
            return False
        if match.command:
            return facts.head in match.command
        return True


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
        match.args_any
        or match.args_regex
        or match.path_any
        or match.path_regex
        or match.subcommand_any
    )


def _path_match_candidates(arg: str) -> tuple[str, ...]:
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
