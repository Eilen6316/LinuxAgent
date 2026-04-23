"""Token-level command safety analysis.

Classifies arbitrary command strings into ``SAFE`` / ``CONFIRM`` / ``BLOCK``
using ``shlex`` tokenization and explicit pattern lists. Substring scans on
``command in string`` are never used: the whole reason v3 was rewritten is
that string-containment checks are trivial to bypass.

Three families of dangerous patterns:

- ``DESTRUCTIVE_COMMANDS``: command names where any invocation warrants
  confirmation (``rm``, ``mkfs``, ``dd``, …). Must be matched against
  ``tokens[0]``, never a substring.
- ``DESTRUCTIVE_ARG_PATTERNS``: argument tokens that escalate danger
  (``-rf``, ``--no-preserve-root``).
- ``DESTRUCTIVE_SUBCOMMAND_PATTERNS``: second-token patterns when the first
  is a known driver (``systemctl stop``, ``kubectl delete``).

Plus a pre-tokenization raw-string scan that catches destructive payloads
smuggled into quoted arguments (``echo "...; rm -rf /"``), and a Unicode
bidirectional-control-character check (TrojanSource attacks).

Modifying the constants below changes HITL coverage; such edits must be
recorded in ``.work/change/`` (see R-HITL-03).
"""

from __future__ import annotations

import re
import shlex
import unicodedata

from ..interfaces import CommandSource, SafetyLevel, SafetyResult

MAX_COMMAND_LENGTH = 2048

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "mkfs",
        "dd",
        "shred",
        "fdisk",
        "parted",
        "wipefs",
        "mkswap",
    }
)

DESTRUCTIVE_ARG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^-[rRfF]*[rRfF][rRfF]+[rRfF]*$"),  # -rf / -Rf / -fr / -rrf …
    re.compile(r"^--no-preserve-root$"),
    re.compile(r"^--force$"),
)

DESTRUCTIVE_SUBCOMMAND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("systemctl", re.compile(r"^(stop|disable|mask|kill|poweroff|reboot|halt)$")),
    ("kubectl", re.compile(r"^(delete|drain|cordon|replace)$")),
    ("docker", re.compile(r"^(rm|rmi|kill|prune|system)$")),
    ("git", re.compile(r"^(push|reset|clean|checkout|rebase)$")),
    ("helm", re.compile(r"^(uninstall|delete|rollback)$")),
)

SENSITIVE_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/etc/shadow(/|$)"),
    re.compile(r"^/etc/gshadow(/|$)"),
    re.compile(r"^/etc/sudoers(/|$)"),
    re.compile(r"^/boot(/|$)"),
    re.compile(r"^/dev/[sh]d[a-z]"),
    re.compile(r"^/dev/nvme\d"),
    re.compile(r"^/proc/(?!self/status|cpuinfo|meminfo|version|loadavg|uptime)"),
    re.compile(r"^/sys/(?!class/net|devices/system/cpu)"),
)

ROOT_PATH_PATTERN = re.compile(r"^/+$")

INTERACTIVE_COMMANDS: frozenset[str] = frozenset(
    {
        "vim",
        "vi",
        "nano",
        "emacs",
        "htop",
        "top",
        "less",
        "more",
        "man",
        "ssh",
        "python",
        "python3",
        "bash",
        "zsh",
        "sh",
        "ipython",
        "mysql",
        "psql",
        "redis-cli",
        "mongo",
    }
)

# Smuggled destructive payloads: scanned against the raw command string
# before tokenization so quoted-argument tricks (``echo "rm -rf /"``) still
# trigger BLOCK.
_EMBEDDED_DANGER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # `rm -rf /` — trailing `/` may be followed by end-of-string, whitespace,
    # or any non-word boundary (e.g. closing quote when smuggled via echo).
    re.compile(r"\brm\s+-[rRfF]{2,}\s+/(?!\w)"),
    re.compile(r"\bmkfs(\.[a-z0-9]+)?\b"),
    re.compile(r"\bdd\s+if="),
    re.compile(r">\s*/dev/(sd[a-z]|nvme\d)"),
    re.compile(r":\s*\(\s*\)\s*\{.*:\s*\|\s*:.*;\s*:"),  # fork bomb
    re.compile(r"\$\("),
    re.compile(r"`[^`]+`"),
)

# Unicode general categories that indicate bidirectional override / isolate
# control characters (TrojanSource class of attacks).
_BIDI_CONTROLS: frozenset[str] = frozenset(
    {"LRE", "RLE", "LRO", "RLO", "LRI", "RLI", "FSI", "PDF", "PDI"}
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InputValidationError(ValueError):
    """Raised when a command fails pre-tokenization input checks."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_input(command: str, *, max_length: int = MAX_COMMAND_LENGTH) -> None:
    """Reject structurally dangerous input before tokenization."""
    if len(command) > max_length:
        raise InputValidationError(f"command exceeds max length ({max_length})")
    if "\x00" in command:
        raise InputValidationError("command contains NUL byte")
    for ch in command:
        if unicodedata.bidirectional(ch) in _BIDI_CONTROLS:
            raise InputValidationError(
                f"command contains bidirectional control character U+{ord(ch):04X}"
            )


def is_interactive(tokens: list[str]) -> bool:
    """Return True when the first token names an interactive command."""
    return bool(tokens) and tokens[0] in INTERACTIVE_COMMANDS


def is_destructive(command: str) -> bool:
    """Public HITL helper: True when ``command`` can never be session-whitelisted.

    R-HITL-03 guarantees destructive commands re-prompt for every execution,
    so any code path that touches the whitelist must gate on this.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return True
    return _tokens_are_destructive(tokens) or _has_embedded_danger(command) is not None


def is_safe(
    command: str,
    *,
    source: CommandSource = CommandSource.USER,
) -> SafetyResult:
    """Classify ``command`` into SAFE / CONFIRM / BLOCK."""
    try:
        validate_input(command)
    except InputValidationError as exc:
        return SafetyResult(
            level=SafetyLevel.BLOCK,
            reason=str(exc),
            matched_rule="INPUT_VALIDATION",
            command_source=source,
        )

    embedded = _has_embedded_danger(command)
    if embedded is not None:
        return SafetyResult(
            level=SafetyLevel.BLOCK,
            reason=f"embedded danger pattern: {embedded}",
            matched_rule="EMBEDDED_DANGER",
            command_source=source,
        )

    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return SafetyResult(
            level=SafetyLevel.BLOCK,
            reason=f"shell parse failed: {exc}",
            matched_rule="PARSE_ERROR",
            command_source=source,
        )
    if not tokens:
        return SafetyResult(
            level=SafetyLevel.BLOCK,
            reason="empty command",
            matched_rule="EMPTY",
            command_source=source,
        )

    targets_root = any(ROOT_PATH_PATTERN.match(t) for t in tokens[1:])
    destructive_arg_present = any(
        pat.match(t) for t in tokens[1:] for pat in DESTRUCTIVE_ARG_PATTERNS
    )
    if targets_root and (_tokens_are_destructive(tokens) or destructive_arg_present):
        return SafetyResult(
            level=SafetyLevel.BLOCK,
            reason="destructive command targeting root filesystem",
            matched_rule="ROOT_PATH",
            command_source=source,
        )

    for tok in tokens[1:]:
        for pat in SENSITIVE_PATH_PATTERNS:
            if pat.match(tok):
                return SafetyResult(
                    level=SafetyLevel.BLOCK,
                    reason=f"sensitive path: {tok}",
                    matched_rule="SENSITIVE_PATH",
                    command_source=source,
                )

    if _tokens_are_destructive(tokens):
        return SafetyResult(
            level=SafetyLevel.CONFIRM,
            reason=f"destructive command: {tokens[0]}",
            matched_rule="DESTRUCTIVE",
            command_source=source,
        )

    for tok in tokens[1:]:
        for pat in DESTRUCTIVE_ARG_PATTERNS:
            if pat.match(tok):
                return SafetyResult(
                    level=SafetyLevel.CONFIRM,
                    reason=f"destructive argument: {tok}",
                    matched_rule="DESTRUCTIVE_ARG",
                    command_source=source,
                )

    if is_interactive(tokens):
        return SafetyResult(
            level=SafetyLevel.CONFIRM,
            reason=f"interactive command: {tokens[0]}",
            matched_rule="INTERACTIVE",
            command_source=source,
        )

    if source is CommandSource.LLM:
        return SafetyResult(
            level=SafetyLevel.CONFIRM,
            reason="LLM-generated command; first run requires approval",
            matched_rule="LLM_FIRST_RUN",
            command_source=source,
        )

    return SafetyResult(level=SafetyLevel.SAFE, command_source=source)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _tokens_are_destructive(tokens: list[str]) -> bool:
    if not tokens:
        return False
    head = tokens[0]
    rest = tokens[1:]
    if head in DESTRUCTIVE_COMMANDS:
        return True
    for cmd, pattern in DESTRUCTIVE_SUBCOMMAND_PATTERNS:
        if head == cmd and rest and pattern.match(rest[0]):
            return True
    return False


def _has_embedded_danger(command: str) -> str | None:
    for pattern in _EMBEDDED_DANGER_PATTERNS:
        if pattern.search(command):
            return pattern.pattern
    return None
