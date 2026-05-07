"""Deterministic LOLBin and interpreter escape detection."""

from __future__ import annotations

from dataclasses import dataclass

from ..interfaces import SafetyLevel
from .shell_structure import ShellStructure, shell_tokens

_NETWORK_FETCHERS: frozenset[str] = frozenset({"curl", "wget"})
_SHELL_INTERPRETERS: frozenset[str] = frozenset({"sh", "bash", "zsh"})
_INTERPRETER_FLAGS: dict[str, frozenset[str]] = {
    "python": frozenset({"-c"}),
    "python3": frozenset({"-c"}),
    "perl": frozenset({"-e"}),
    "ruby": frozenset({"-e"}),
    "node": frozenset({"-e"}),
}
_EDITOR_ESCAPE_COMMANDS: frozenset[str] = frozenset(
    {"vim", "vi", "nano", "emacs", "less", "more", "man"}
)
_XARGS_DANGEROUS_HEADS: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "shred",
        "wipefs",
        "sh",
        "bash",
        "zsh",
        "python",
        "python3",
        "perl",
        "ruby",
        "node",
    }
)


@dataclass(frozen=True)
class LolbinFinding:
    level: SafetyLevel
    risk_score: int
    capability: str
    matched_rule: str
    reason: str


def analyze_lolbins(tokens: tuple[str, ...], shell: ShellStructure) -> tuple[LolbinFinding, ...]:
    findings: list[LolbinFinding] = []
    findings.extend(_network_to_shell_findings(shell))
    findings.extend(_interpreter_findings(tokens))
    findings.extend(_find_exec_findings(tokens))
    findings.extend(_xargs_findings(tokens))
    findings.extend(_text_processing_findings(tokens))
    findings.extend(_editor_escape_findings(tokens))
    return tuple(findings)


def _network_to_shell_findings(shell: ShellStructure) -> tuple[LolbinFinding, ...]:
    if not shell.pipeline_segments:
        return ()
    heads = tuple(_segment_head(segment) for segment in shell.pipeline_segments)
    has_fetcher = any(head in _NETWORK_FETCHERS for head in heads)
    has_shell = any(head in _SHELL_INTERPRETERS for head in heads)
    if has_fetcher and has_shell:
        return (
            _finding(
                SafetyLevel.BLOCK,
                100,
                "shell.remote_execute",
                "LOLBIN_NETWORK_TO_SHELL",
                "network output piped into shell interpreter",
            ),
        )
    return ()


def _segment_head(segment: str) -> str | None:
    try:
        parts = shell_tokens(segment)
    except ValueError:
        return None
    return parts[0] if parts else None


def _interpreter_findings(tokens: tuple[str, ...]) -> tuple[LolbinFinding, ...]:
    if not tokens:
        return ()
    head = tokens[0]
    if head in _SHELL_INTERPRETERS and _has_shell_c(tokens):
        return (_interpreter_finding("LOLBIN_SHELL_C", "shell command string execution"),)
    flags = _INTERPRETER_FLAGS.get(head)
    if flags is not None and any(_flag_matches(arg, flags) for arg in tokens[1:]):
        return (
            _interpreter_finding(f"LOLBIN_{head.upper()}_EXEC", f"{head} inline code execution"),
        )
    return ()


def _has_shell_c(tokens: tuple[str, ...]) -> bool:
    return any(arg == "-c" or (arg.startswith("-") and "c" in arg[1:]) for arg in tokens[1:])


def _flag_matches(arg: str, flags: frozenset[str]) -> bool:
    return arg in flags or any(arg.startswith(flag) and len(arg) > len(flag) for flag in flags)


def _interpreter_finding(matched_rule: str, reason: str) -> LolbinFinding:
    return _finding(
        SafetyLevel.CONFIRM,
        90,
        "interpreter.escape",
        matched_rule,
        reason,
    )


def _find_exec_findings(tokens: tuple[str, ...]) -> tuple[LolbinFinding, ...]:
    if not tokens or tokens[0] != "find":
        return ()
    if "-exec" in tokens or "-execdir" in tokens:
        return (
            _finding(
                SafetyLevel.CONFIRM,
                85,
                "lolbin.find_exec",
                "LOLBIN_FIND_EXEC",
                "find can execute arbitrary commands through -exec",
            ),
        )
    return ()


def _xargs_findings(tokens: tuple[str, ...]) -> tuple[LolbinFinding, ...]:
    if not tokens or tokens[0] != "xargs":
        return ()
    invoked = _xargs_invoked_head(tokens)
    if invoked in _XARGS_DANGEROUS_HEADS:
        return (
            _finding(
                SafetyLevel.CONFIRM,
                85,
                "lolbin.xargs_exec",
                "LOLBIN_XARGS_EXEC",
                "xargs can invoke a dangerous command from input",
            ),
        )
    return ()


def _xargs_invoked_head(tokens: tuple[str, ...]) -> str | None:
    index = 1
    while index < len(tokens):
        arg = tokens[index]
        if arg == "--":
            return tokens[index + 1] if index + 1 < len(tokens) else None
        if arg.startswith("-"):
            index += _xargs_option_width(arg, tokens[index + 1 :])
            continue
        return arg
    return None


def _xargs_option_width(arg: str, remaining: tuple[str, ...]) -> int:
    if arg in {"-I", "-E", "-n", "-P", "-s"} and remaining:
        return 2
    return 1


def _text_processing_findings(tokens: tuple[str, ...]) -> tuple[LolbinFinding, ...]:
    if not tokens:
        return ()
    if tokens[0] == "awk" and any("system(" in arg for arg in tokens[1:]):
        return (_text_finding("LOLBIN_AWK_SYSTEM", "awk system() can execute commands"),)
    if tokens[0] == "sed" and any(_sed_exec_arg(arg) for arg in tokens[1:]):
        return (_text_finding("LOLBIN_SED_EXEC", "sed e command can execute shell commands"),)
    return ()


def _sed_exec_arg(arg: str) -> bool:
    return arg.endswith("e") or " e " in f" {arg} " or "\ne" in arg


def _text_finding(matched_rule: str, reason: str) -> LolbinFinding:
    return _finding(SafetyLevel.CONFIRM, 80, "lolbin.text_exec", matched_rule, reason)


def _editor_escape_findings(tokens: tuple[str, ...]) -> tuple[LolbinFinding, ...]:
    if tokens and tokens[0] in _EDITOR_ESCAPE_COMMANDS:
        return (
            _finding(
                SafetyLevel.CONFIRM,
                70,
                "lolbin.interactive_escape",
                "LOLBIN_INTERACTIVE_ESCAPE",
                "interactive editor or pager can escape to shell",
            ),
        )
    return ()


def _finding(
    level: SafetyLevel,
    risk_score: int,
    capability: str,
    matched_rule: str,
    reason: str,
) -> LolbinFinding:
    return LolbinFinding(
        level=level,
        risk_score=risk_score,
        capability=capability,
        matched_rule=matched_rule,
        reason=reason,
    )
