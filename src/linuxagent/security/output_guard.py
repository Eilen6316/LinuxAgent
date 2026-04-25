"""Guard command output before it is sent to an LLM."""

from __future__ import annotations

from dataclasses import dataclass

from ..interfaces import ExecutionResult
from .redaction import redact_text

GUARDED_OUTPUT_MAX_CHARS = 8000


@dataclass(frozen=True)
class GuardedOutput:
    text: str
    redacted_count: int
    truncated: bool


def guard_execution_result(
    result: ExecutionResult,
    *,
    max_chars: int = GUARDED_OUTPUT_MAX_CHARS,
) -> GuardedOutput:
    """Return a redacted, bounded representation safe for provider analysis."""
    raw = (
        f"command={result.command!r}\n"
        f"exit_code={result.exit_code}\n"
        f"stdout={result.stdout.rstrip()}\n"
        f"stderr={result.stderr.rstrip()}"
    )
    redacted = redact_text(raw)
    truncated = len(redacted.text) > max_chars
    text = redacted.text[:max_chars] if truncated else redacted.text
    if truncated:
        text = f"{text}\n[output truncated to {max_chars} chars before LLM analysis]"
    return GuardedOutput(
        text=f"{text}\nredacted_count={redacted.count}\ntruncated={str(truncated).lower()}",
        redacted_count=redacted.count,
        truncated=truncated,
    )
