"""Sensitive-data redaction for LLM-bound text and local records."""

from __future__ import annotations

import re
from collections.abc import Iterable
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
        # Credential key names whose ``_``-split parts are individually benign
        # (``access_key`` -> access/key), so they need explicit listing. ``_key``
        # is intentionally NOT a blanket suffix — it would redact lookup keys
        # such as ``cache_key``/``prompt_cache_key``.
        "access_key",
        "accesskey",
        "secret_key",
        "private_key",
        "x_api_key",
        "x_goog_api_key",
        "bearer",
    }
)

_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_INCOMPLETE_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*",
    re.DOTALL,
)
_PRIVATE_KEY_BEGIN_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PRIVATE_KEY_END_RE = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")

# Structured key/value secrets, dispatched by pattern identity in ``_replacement``.
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*:\s*)(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
# Keyword assignments. The leading ``[A-Za-z0-9_]*`` lets compound names match
# (``DB_PASSWORD=``, ``service_api_key=``); the optional quote before the
# separator handles JSON/YAML (``"password": "..."``); and the value accepts a
# quoted run so spaces inside quotes do not truncate the redaction.
_KEYWORD_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])"
    r"([A-Za-z0-9_]*(?:password|passwd|pwd|token|api[-_]?key|secret)[A-Za-z0-9_]*)"
    r"[\"']?\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s&;,]+)"
)
_IDENTIFIED_BY_RE = re.compile(r"(?i)\b(identified\s+by\s+)(['\"]?)[^\s;'\",]+(['\"]?)")
# Credentialed connection strings of any scheme, including the username-less
# ``redis://:pass@`` form and ``mongodb+srv://`` variants.
_CONNECTION_STRING_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9+.\-])([A-Za-z][A-Za-z0-9+.\-]*://[^:@/\s]*:)[^@\s]+(@)"
)
# Opaque vendor tokens redacted whole, including Google/Gemini (``AIza...``) and
# GLM/Zhipu (``<32-hex>.<16-alnum>``) keys for the providers LinuxAgent supports.
_OPAQUE_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\b[0-9a-f]{32}\.[A-Za-z0-9]{16}\b"),
)
_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    _AUTH_HEADER_RE,
    _KEYWORD_ASSIGNMENT_RE,
    _IDENTIFIED_BY_RE,
    _CONNECTION_STRING_RE,
    *_OPAQUE_TOKEN_PATTERNS,
)
_RAW_COMMAND_KEYS: frozenset[str] = frozenset({"command", "command_tokens", "command_head"})


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int


def redact_text(text: str) -> RedactionResult:
    """Redact common secrets from free-form text."""
    updated, count = _PRIVATE_KEY_PATTERN.subn(REDACTED, text)
    updated, incomplete_count = _INCOMPLETE_PRIVATE_KEY_PATTERN.subn(REDACTED, updated)
    count += incomplete_count
    for pattern in _TEXT_PATTERNS:
        updated, n = pattern.subn(_replacement, updated)
        count += n
    return RedactionResult(text=updated, count=count)


def redact_lines(lines: Iterable[str]) -> list[str]:
    """Redact a sequence of *contiguous* lines, carrying private-key block state.

    ``redact_text`` only collapses a PEM block when its BEGIN and END markers are
    in the same string; applied to one line at a time it redacts just the BEGIN
    line and leaks the base64 body and END line. Track the open block so every
    line from BEGIN through END is redacted, while preserving line structure.

    Only safe for contiguous content (e.g. a read window); do not use on
    non-contiguous search matches, where the block state would mis-fire.
    """
    output: list[str] = []
    in_private_key = False
    for line in lines:
        if in_private_key:
            output.append(REDACTED)
            if _PRIVATE_KEY_END_RE.search(line):
                in_private_key = False
            continue
        output.append(redact_text(line).text)
        if _PRIVATE_KEY_BEGIN_RE.search(line) and not _PRIVATE_KEY_END_RE.search(line):
            in_private_key = True
    return output


def redact_record(record: dict[str, Any], *, redact_commands: bool = False) -> dict[str, Any]:
    """Recursively redact sensitive record fields before persistence.

    Audit commands intentionally remain raw for traceability in the local
    ``0o600`` log; other strings are scanned because logs and provider errors
    often embed headers or tokens in free-form text. Set ``redact_commands`` when
    the record leaves the host (e.g. a remote audit sink) so inline command
    secrets are scrubbed even though the local copy keeps them raw.
    """
    redacted, _count = _redact_value(record, key=None, redact_commands=redact_commands)
    return redacted if isinstance(redacted, dict) else {}


def _redact_value(value: Any, *, key: str | None, redact_commands: bool) -> tuple[Any, int]:
    if key is not None and _is_sensitive_key(key):
        return REDACTED, 1
    keep_raw = key in _RAW_COMMAND_KEYS and not redact_commands
    if isinstance(value, dict):
        total = 0
        output_record: dict[str, Any] = {}
        for child_key, child_value in value.items():
            redacted, count = _redact_value(
                child_value, key=str(child_key), redact_commands=redact_commands
            )
            output_record[str(child_key)] = redacted
            total += count
        return output_record, total
    if isinstance(value, list):
        if keep_raw:
            return value, 0
        total = 0
        output_list: list[Any] = []
        for item in value:
            redacted, count = _redact_value(item, key=None, redact_commands=redact_commands)
            output_list.append(redacted)
            total += count
        return output_list, total
    if isinstance(value, str):
        if keep_raw:
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
    # Dispatch by pattern identity, not by sniffing the matched text: a value
    # that happens to contain "://" must not be mistaken for the connection
    # string pattern (which would index a non-existent second group).
    pattern = match.re
    if pattern is _AUTH_HEADER_RE:
        return f"{match.group(1)}{REDACTED}"
    if pattern is _CONNECTION_STRING_RE:
        return f"{match.group(1)}{REDACTED}{match.group(2)}"
    if pattern is _KEYWORD_ASSIGNMENT_RE:
        return f"{match.group(1)}={REDACTED}"
    if pattern is _IDENTIFIED_BY_RE:
        return f"{match.group(1)}{match.group(2)}{REDACTED}{match.group(3)}"
    return REDACTED
