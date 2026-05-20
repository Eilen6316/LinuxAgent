"""On-demand context injection helpers for graph prompts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .operating_manifest import operating_manifest_context
from .runtime_events import RuntimeEvent, context_runtime_event


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


def load_linuxagent_manual() -> str:
    return operating_manifest_context()


def linuxagent_manual_context(
    reason: str, *, loader: ManualLoader | None = None
) -> ContextInjection:
    content = (loader or load_linuxagent_manual)()
    return ContextInjection(
        source=ContextSource.LINUXAGENT_MANUAL,
        reason=reason,
        content=content,
        summary=_summary(content),
    )


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


def manual_prompt_context(product_context: str, injection: ContextInjection | None) -> str:
    if injection is None or not injection.content.strip():
        return product_context
    return f"{product_context}\n\n{injection.content}"


def _summary(content: str) -> str:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return "empty context"
    return lines[0][:160]
