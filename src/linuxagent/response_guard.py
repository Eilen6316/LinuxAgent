"""Lightweight final-response guardrails."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass

from .i18n import Translator, default_translator
from .interfaces import CommandSource, SafetyLevel
from .policy import DEFAULT_POLICY_ENGINE, PolicyEngine
from .policy.display import policy_display_reason
from .security import redact_text

_CODE_FENCE_RE = re.compile(r"```(?P<lang>[^\n]*)\n(?P<body>.*?)```", re.DOTALL)
_EXPLICIT_SHELL_FENCE_LANGS = frozenset({"bash", "sh", "shell", "zsh"})
_AMBIGUOUS_COMMAND_FENCE_LANGS = frozenset({"", "console", "text"})
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_DANGEROUS_LINE_RE = re.compile(
    r"(?im)^\s*(?:\$|#|sudo\s+)?(?:rm|mkfs(?:\.[\w-]+)?|dd|shred|curl|wget|cat)\b[^\n]*$"
)
_INCOMPLETE_SHELL_TAIL_TOKENS = frozenset(
    {"|", "||", "&", "&&", ";", "<", "<<", "<<<", ">", ">>", ">|", "<>", "&>", "&>>"}
)
_PROMPT_INJECTION_LINE_RE = re.compile(
    r"(?im)^.*\b("
    r"ignore (?:all )?(?:previous|prior|above) (?:instructions|messages|rules)|"
    r"disregard (?:all )?(?:previous|prior|above) (?:instructions|messages|rules)|"
    r"system prompt|developer message|reveal .*instructions|"
    r"忽略(?:以上|之前|前面).*(?:指令|规则|消息)|"
    r"泄露.*(?:系统提示|开发者消息|指令)"
    r")\b.*$"
)


@dataclass(frozen=True)
class ResponseGuardResult:
    text: str
    redacted_count: int = 0
    blocked_reason: str | None = None
    injection_lines_removed: int = 0

    @property
    def changed(self) -> bool:
        return (
            self.redacted_count > 0
            or self.blocked_reason is not None
            or self.injection_lines_removed > 0
        )


def guard_response_text(
    text: str,
    *,
    injection_replacement: str = "[removed unsafe tool-output instruction]",
    blocked_response: Callable[[str], str] | None = None,
    policy_engine: PolicyEngine = DEFAULT_POLICY_ENGINE,
    translator: Translator | None = None,
) -> ResponseGuardResult:
    """Redact and block unsafe final assistant output without calling an LLM."""
    tr = translator or default_translator()
    redacted = redact_text(text)
    injection_guarded, injection_count = _remove_prompt_injection_lines(
        redacted.text,
        replacement=injection_replacement,
    )
    blocked = _blocked_command_suggestion(injection_guarded, policy_engine=policy_engine)
    if blocked is not None:
        reason = (
            policy_display_reason(blocked.reason, blocked.matched_rules, tr)
            or blocked.reason
            or blocked.command
        )
        return ResponseGuardResult(
            text=blocked_response(reason)
            if blocked_response is not None
            else _blocked_text(reason),
            redacted_count=redacted.count,
            blocked_reason=reason,
            injection_lines_removed=injection_count,
        )
    return ResponseGuardResult(
        text=injection_guarded,
        redacted_count=redacted.count,
        injection_lines_removed=injection_count,
    )


@dataclass(frozen=True)
class _BlockedCommandSuggestion:
    command: str
    reason: str | None
    matched_rules: tuple[str, ...] = ()


def _blocked_text(reason: str) -> str:
    return (
        "LinuxAgent blocked the final response because it suggested a command "
        f"that violates the command safety policy: {reason}"
    )


def _remove_prompt_injection_lines(text: str, *, replacement: str) -> tuple[str, int]:
    updated, count = _PROMPT_INJECTION_LINE_RE.subn(replacement, text)
    return updated, count


def _blocked_command_suggestion(
    text: str,
    *,
    policy_engine: PolicyEngine,
) -> _BlockedCommandSuggestion | None:
    for command in _candidate_commands(text):
        decision = policy_engine.evaluate(command, source=CommandSource.USER)
        if decision.level is SafetyLevel.BLOCK:
            return _BlockedCommandSuggestion(
                command=command,
                reason=decision.reason,
                matched_rules=decision.matched_rules,
            )
    return None


def _candidate_commands(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    candidates.extend(_commands_from_code_fences(text))
    candidates.extend(_commands_from_inline_code(text))
    candidates.extend(_commands_from_dangerous_lines(text))
    return tuple(dict.fromkeys(_normalize_command(candidate) for candidate in candidates))


def _commands_from_code_fences(text: str) -> list[str]:
    commands: list[str] = []
    for match in _CODE_FENCE_RE.finditer(text):
        language = _fence_language(match.group("lang"))
        body_lines = match.group("body").splitlines()
        if language in _EXPLICIT_SHELL_FENCE_LANGS:
            commands.extend(_commands_from_shell_lines(body_lines, allow_incomplete=True))
        elif language in _AMBIGUOUS_COMMAND_FENCE_LANGS:
            commands.extend(_commands_from_ambiguous_lines(body_lines))
    return commands


def _fence_language(language: str) -> str:
    return language.strip().lower()


def _without_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text)


def _commands_from_inline_code(text: str) -> list[str]:
    return [
        command
        for match in _INLINE_CODE_RE.finditer(text)
        if (command := _shell_command_line(match.group(1), allow_incomplete=False)) is not None
    ]


def _commands_from_dangerous_lines(text: str) -> list[str]:
    scan_text = _without_code_fences(text)
    return [
        command
        for match in _DANGEROUS_LINE_RE.finditer(scan_text)
        if (command := _shell_command_line(match.group(0), allow_incomplete=False)) is not None
    ]


def _commands_from_shell_lines(lines: list[str], *, allow_incomplete: bool) -> list[str]:
    return [
        command
        for line in lines
        if (command := _shell_command_line(line, allow_incomplete=allow_incomplete)) is not None
    ]


def _commands_from_ambiguous_lines(lines: list[str]) -> list[str]:
    commands: list[str] = []
    for line in lines:
        if line.lstrip().startswith(("$ ", "# ")):
            command = _shell_command_line(line, allow_incomplete=True)
        elif _DANGEROUS_LINE_RE.match(line):
            command = _shell_command_line(line, allow_incomplete=False)
        else:
            command = None
        if command is not None:
            commands.append(command)
    return commands


def _shell_command_line(line: str, *, allow_incomplete: bool) -> str | None:
    command = _normalize_command(line)
    if not command:
        return None
    if command.startswith(("$ ", "# ")):
        command = command[2:].strip()
    if not command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    if not allow_incomplete and tokens[-1] in _INCOMPLETE_SHELL_TAIL_TOKENS:
        return None
    if not _looks_like_command(tokens):
        return None
    return command


def _normalize_command(command: str) -> str:
    return command.strip().removeprefix("sudo ").strip()


def _looks_like_command(tokens: list[str]) -> bool:
    head = tokens[0]
    if head in {"sudo", "doas", "env", "command", "time"}:
        return len(tokens) > 1 and _looks_like_command(tokens[1:])
    if head.startswith(("/", "./", "../", "~")):
        return True
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", head):
        return False
    return any(ch.isalpha() for ch in head)
