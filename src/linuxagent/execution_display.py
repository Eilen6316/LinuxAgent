"""Redacted execution-result text for UI display and LLM context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .interfaces import ExecutionResult
from .security.redaction import redact_text

EXECUTION_DISPLAY_MAX_CHARS = 8000
EXECUTION_SUMMARY_OUTPUT_PREVIEW_CHARS = 900


@dataclass(frozen=True)
class ExecutionDisplay:
    text: str
    redacted_count: int
    truncated: bool


def execution_display_text(
    result: ExecutionResult,
    *,
    max_chars: int = EXECUTION_DISPLAY_MAX_CHARS,
    include_output: bool = True,
) -> ExecutionDisplay:
    stdout = result.stdout.rstrip() if include_output else "[streamed above]"
    stderr = result.stderr.rstrip() if include_output else "[streamed above]"
    raw = "\n".join(
        (
            f"command: {result.command}",
            f"exit_code: {result.exit_code}",
            f"duration_seconds: {result.duration:.3f}",
            f"sandbox: {_sandbox_line(result)}",
            f"remote: {_remote_line(result.remote)}",
            "stdout:",
            stdout,
            "stderr:",
            stderr,
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


def execution_summary_text(
    result: ExecutionResult,
    *,
    max_preview_chars: int = EXECUTION_SUMMARY_OUTPUT_PREVIEW_CHARS,
) -> ExecutionDisplay:
    preview = _output_preview(result, max_chars=max_preview_chars)
    metadata = "\n".join(
        (
            f"command: {result.command}",
            f"exit_code: {result.exit_code}",
            f"duration_seconds: {result.duration:.3f}",
            f"sandbox: {_sandbox_line(result)}",
            f"remote: {_remote_line(result.remote)}",
            _stream_stats("stdout", result.stdout),
            _stream_stats("stderr", result.stderr),
        )
    )
    redacted = redact_text(metadata)
    return ExecutionDisplay(
        text=f"{redacted.text}\n{preview.text}",
        redacted_count=redacted.count + preview.redacted_count,
        truncated=preview.truncated,
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


def _stream_stats(name: str, value: str) -> str:
    if not value:
        return f"{name}: 0 chars, 0 lines"
    line_count = len(value.splitlines()) or 1
    return f"{name}: {len(value)} chars, {line_count} lines"


def _output_preview(result: ExecutionResult, *, max_chars: int) -> ExecutionDisplay:
    output = _combined_output(result).strip()
    if not output:
        return ExecutionDisplay("preview: <empty>", redacted_count=0, truncated=False)
    redacted = redact_text(output)
    truncated = len(redacted.text) > max_chars
    preview = redacted.text[:max_chars] if truncated else redacted.text
    suffix = "\n[preview truncated]" if truncated else ""
    return ExecutionDisplay(
        f"preview:\n{preview}{suffix}",
        redacted_count=redacted.count,
        truncated=truncated,
    )


def _combined_output(result: ExecutionResult) -> str:
    parts = []
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    return "\n".join(parts)
