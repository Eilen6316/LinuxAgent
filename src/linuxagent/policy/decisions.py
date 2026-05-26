"""Policy decision construction and merge helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..interfaces import CommandSource, SafetyLevel
from .lolbins import LolbinFinding
from .models import ApprovalMode, PolicyApproval, PolicyDecision, PolicyRule
from .rule_matcher import path_match_candidates
from .shell_structure import ShellRedirect, ShellStructure

_LEVEL_RANK = {SafetyLevel.SAFE: 0, SafetyLevel.CONFIRM: 1, SafetyLevel.BLOCK: 2}
_SENSITIVE_REDIRECT_PATHS: tuple[str, ...] = (
    r"^/etc(/|$)",
    r"^/root(/|$)",
    r"^/boot(/|$)",
    r"^/dev/[sh]d[a-z]",
    r"^/dev/nvme\d",
    r"^/home/[^/]+/\.ssh(/|$)",
)


def decision_from_matches(matches: list[PolicyRule], source: CommandSource) -> PolicyDecision:
    max_level = max_level_for(rule.level for rule in matches)
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
        approval=approval_for(max_level, matched_rules),
        command_source=source,
        can_whitelist=not any(rule.never_whitelist for rule in matches),
    )


def decision_from_shell_structure(
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


def decision_from_lolbins(
    findings: tuple[LolbinFinding, ...],
    source: CommandSource,
) -> PolicyDecision:
    if not findings:
        return PolicyDecision(level=SafetyLevel.SAFE, command_source=source)
    max_level = max_level_for(finding.level for finding in findings)
    matched_rules = tuple(dict.fromkeys(finding.matched_rule for finding in findings))
    return PolicyDecision(
        level=max_level,
        risk_score=max(finding.risk_score for finding in findings),
        capabilities=tuple(dict.fromkeys(finding.capability for finding in findings)),
        matched_rules=matched_rules,
        reason="; ".join(dict.fromkeys(finding.reason for finding in findings)),
        approval=approval_for(max_level, matched_rules),
        command_source=source,
        can_whitelist=False,
    )


def merge_decisions(
    decisions: Iterable[PolicyDecision],
    source: CommandSource,
) -> PolicyDecision:
    materialized = tuple(decisions)
    max_level = max_level_for(decision.level for decision in materialized)
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
        approval=approval_for(max_level, matched_rules),
        command_source=source,
        can_whitelist=all(decision.can_whitelist for decision in materialized),
    )


def max_level_for(levels: Iterable[SafetyLevel]) -> SafetyLevel:
    return max(levels, key=lambda level: _LEVEL_RANK[level])


def approval_for(level: SafetyLevel, matched_rules: tuple[str, ...]) -> PolicyApproval:
    if level is SafetyLevel.CONFIRM:
        mode = (
            ApprovalMode.BATCH_OPERATOR
            if "BATCH_CONFIRM" in matched_rules
            else ApprovalMode.SINGLE_OPERATOR
        )
        return PolicyApproval(required=True, mode=mode)
    return PolicyApproval()


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
        approval=approval_for(level, matched_rules),
        command_source=source,
        can_whitelist=level is not SafetyLevel.BLOCK,
    )


def _is_sensitive_redirect_target(target: str) -> bool:
    return any(
        re.match(pattern, candidate)
        for candidate in path_match_candidates(target)
        for pattern in _SENSITIVE_REDIRECT_PATHS
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
