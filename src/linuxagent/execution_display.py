"""Redacted execution-result text for UI display and LLM context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .interfaces import ExecutionResult
from .security.redaction import redact_text

EXECUTION_DISPLAY_MAX_CHARS = 8000


@dataclass(frozen=True)
class ExecutionDisplay:
    text: str
    redacted_count: int
    truncated: bool


def execution_display_text(
    result: ExecutionResult,
    *,
    max_chars: int = EXECUTION_DISPLAY_MAX_CHARS,
) -> ExecutionDisplay:
    raw = "\n".join(
        (
            f"command: {result.command}",
            f"exit_code: {result.exit_code}",
            f"duration_seconds: {result.duration:.3f}",
            f"sandbox: {_sandbox_line(result)}",
            f"remote: {_remote_line(result.remote)}",
            "stdout:",
            result.stdout.rstrip(),
            "stderr:",
            result.stderr.rstrip(),
        )
    )
    redacted = redact_text(raw)
    truncated = len(redacted.text) > max_chars
    text = redacted.text[:max_chars] if truncated else redacted.text
    if truncated:
        text = f"{text}\n[output truncated to {max_chars} chars before display/context]"
    return ExecutionDisplay(
        text=f"{text}\nredacted_count: {redacted.count}\ntruncated: {str(truncated).lower()}",
        redacted_count=redacted.count,
        truncated=truncated,
    )


def _sandbox_line(result: ExecutionResult) -> str:
    sandbox = result.sandbox
    if sandbox is None:
        return "none"
    fallback = f" fallback={sandbox.fallback_reason}" if sandbox.fallback_reason else ""
    return (
        f"profile={sandbox.requested_profile.value} runner={sandbox.runner.value} "
        f"enabled={_yes_no(sandbox.enabled)} enforced={_yes_no(sandbox.enforced)} "
        f"network={sandbox.network.value}{fallback}"
    )


def _remote_line(remote: dict[str, Any] | None) -> str:
    if not remote:
        return "none"
    remote_type = str(remote.get("type") or "unknown")
    hosts = remote.get("hosts")
    if not isinstance(hosts, list):
        return remote_type
    return f"{remote_type} hosts={len(hosts)}"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
