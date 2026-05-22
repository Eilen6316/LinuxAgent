"""On-demand context injection helpers for graph prompts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .operating_manifest import operating_manifest_context
from .runtime_events import RuntimeEvent, context_runtime_event

MAX_CONTEXT_CHARS = 12_000
MAX_SUMMARY_CHARS = 160
AGENTS_FILENAMES = ("AGENTS.md",)
WORKSPACE_SUMMARY_FILENAMES = ("README.md", "pyproject.toml")


class ContextSource(StrEnum):
    LINUXAGENT_MANUAL = "linuxagent-manual"
    AGENTS = "agents"
    WORKSPACE_SUMMARY = "workspace-summary"


@dataclass(frozen=True)
class ContextInjection:
    source: ContextSource
    reason: str
    content: str
    summary: str

    @property
    def budget(self) -> dict[str, int]:
        return {"characters": len(self.content)}


ManualLoader = Callable[[], str]
ContextLoader = Callable[[], str]


def load_linuxagent_manual() -> str:
    return operating_manifest_context()


def linuxagent_manual_context(
    reason: str, *, loader: ManualLoader | None = None
) -> ContextInjection:
    content = (loader or load_linuxagent_manual)()
    return context_injection(
        ContextSource.LINUXAGENT_MANUAL,
        reason=reason,
        content=content,
    )


def agents_context(
    reason: str,
    *,
    workspace_root: Path,
    loader: ContextLoader | None = None,
) -> ContextInjection:
    content = (loader or (lambda: load_agents_context(workspace_root)))()
    return context_injection(ContextSource.AGENTS, reason=reason, content=content)


def workspace_summary_context(
    reason: str,
    *,
    workspace_root: Path,
    loader: ContextLoader | None = None,
) -> ContextInjection:
    content = (loader or (lambda: load_workspace_summary_context(workspace_root)))()
    return context_injection(ContextSource.WORKSPACE_SUMMARY, reason=reason, content=content)


def context_injection(
    source: ContextSource,
    *,
    reason: str,
    content: str,
) -> ContextInjection:
    normalized = _truncate_context(content.strip())
    return ContextInjection(
        source=source,
        reason=reason,
        content=normalized,
        summary=_summary(normalized),
    )


def load_agents_context(workspace_root: Path) -> str:
    return _load_first_existing(workspace_root, AGENTS_FILENAMES)


def load_workspace_summary_context(workspace_root: Path) -> str:
    parts = []
    for filename in WORKSPACE_SUMMARY_FILENAMES:
        content = _load_text_file(workspace_root / filename)
        if content:
            parts.append(f"# {filename}\n{content}")
    return "\n\n".join(parts)


def context_injected_event(
    injection: ContextInjection,
    *,
    thread_id: str,
    turn_id: str,
) -> RuntimeEvent:
    return context_runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        phase="injected",
        source=injection.source.value,
        reason=injection.reason,
        budget=injection.budget,
        summary=injection.summary,
    )


def context_skipped_event(
    *,
    source: ContextSource,
    reason: str,
    summary: str,
    thread_id: str,
    turn_id: str,
) -> RuntimeEvent:
    return context_runtime_event(
        thread_id=thread_id,
        turn_id=turn_id,
        phase="skipped",
        source=source.value,
        reason=reason,
        summary=summary,
    )


def prompt_context(product_context: str, *injections: ContextInjection | None) -> str:
    content = "\n\n".join(
        injection.content
        for injection in injections
        if injection is not None and injection.content.strip()
    )
    if not content:
        return product_context
    return f"{product_context}\n\n{content}"


def manual_prompt_context(product_context: str, injection: ContextInjection | None) -> str:
    return prompt_context(product_context, injection)


def _load_first_existing(workspace_root: Path, filenames: tuple[str, ...]) -> str:
    for filename in filenames:
        content = _load_text_file(workspace_root / filename)
        if content:
            return content
    return ""


def _load_text_file(path: Path) -> str:
    try:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _truncate_context(content: str) -> str:
    if len(content) <= MAX_CONTEXT_CHARS:
        return content
    return content[:MAX_CONTEXT_CHARS]


def _summary(content: str) -> str:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return "empty context"
    return lines[0][:MAX_SUMMARY_CHARS]
