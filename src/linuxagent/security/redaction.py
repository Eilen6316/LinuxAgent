"""Sensitive-data redaction for LLM-bound text and local records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

REDACTED = "***redacted***"

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
    }
)

_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*:\s*)(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(password|passwd|pwd|token|api[_-]?key|secret)\s*[:=]\s*[^\s&;,]+"),
    re.compile(r"(?i)\b(identified\s+by\s+)(['\"]?)[^\s;'\",]+(['\"]?)"),
    re.compile(r"(?i)\b((?:postgres(?:ql)?|mysql|mariadb|redis|mongodb)://[^:\s/@]+:)[^@\s]+(@)"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int


def redact_text(text: str) -> RedactionResult:
    """Redact common secrets from free-form text."""
    updated, count = _PRIVATE_KEY_PATTERN.subn(REDACTED, text)
    for pattern in _TEXT_PATTERNS:
        updated, n = pattern.subn(_replacement, updated)
        count += n
    return RedactionResult(text=updated, count=count)


def redact_record(record: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive record fields before persistence.

    Audit commands intentionally remain raw for traceability; other strings are
    scanned because logs and provider errors often embed headers or tokens in
    free-form text.
    """
    redacted, _count = _redact_value(record, key=None)
    return redacted if isinstance(redacted, dict) else {}


def _redact_value(value: Any, *, key: str | None) -> tuple[Any, int]:
    if key is not None and _is_sensitive_key(key):
        return REDACTED, 1
    if isinstance(value, dict):
        total = 0
        output_record: dict[str, Any] = {}
        for child_key, child_value in value.items():
            redacted, count = _redact_value(child_value, key=str(child_key))
            output_record[str(child_key)] = redacted
            total += count
        return output_record, total
    if isinstance(value, list):
        total = 0
        output_list: list[Any] = []
        for item in value:
            redacted, count = _redact_value(item, key=None)
            output_list.append(redacted)
            total += count
        return output_list, total
    if isinstance(value, str):
        if key == "command":
            return value, 0
        result = redact_text(value)
        return result.text, result.count
    return value, 0


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        part in _SENSITIVE_KEYS for part in normalized.split("_")
    )


def _replacement(match: re.Match[str]) -> str:
    groups = match.groups()
    if groups and match.re.pattern.startswith("(?i)(authorization"):
        return f"{groups[0]}{REDACTED}"
    if groups and "://" in match.group(0):
        return f"{groups[0]}{REDACTED}{groups[1]}"
    if groups and match.re.pattern.startswith("(?i)\\b(password"):
        return f"{groups[0]}={REDACTED}"
    if groups and match.re.pattern.startswith("(?i)\\b(identified"):
        return f"{groups[0]}{groups[1]}{REDACTED}{groups[2]}"
    return REDACTED
