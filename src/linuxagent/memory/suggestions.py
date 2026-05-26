"""Deterministic pending memory suggestions from local chat history."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import BaseMessage

from ..security import redact_text
from ..services import ChatService
from .store import MemoryStore, MemorySuggestion


@dataclass(frozen=True)
class MemorySuggestionResult:
    suggestion: MemorySuggestion | None
    session_count: int


def suggest_from_history(
    memory_store: MemoryStore,
    chat_service: ChatService,
    *,
    session_limit: int = 5,
) -> MemorySuggestionResult:
    """Write a pending, user-reviewable memory candidate from saved sessions."""
    sessions = chat_service.list_sessions(limit=session_limit)
    if not sessions:
        return MemorySuggestionResult(suggestion=None, session_count=0)
    lines = [
        "Review this pending memory before promotion. It was generated from local chat history.",
        "Promote only stable operator/project preferences or recurring operational context.",
        "",
    ]
    for session in sessions:
        lines.extend(
            [
                f"## Session: {redact_text(session.title).text}",
                f"thread_id: {session.thread_id}",
                f"updated_at: {session.updated_at.isoformat()}",
                "",
            ]
        )
        snippets = _message_snippets(session.messages)
        if snippets:
            lines.extend(snippets)
        else:
            lines.append("- No textual snippets available.")
        lines.append("")
    suggestion = memory_store.add_suggestion(
        "\n".join(lines).strip(),
        title="Pending memory from chat history",
    )
    return MemorySuggestionResult(suggestion=suggestion, session_count=len(sessions))


def _message_snippets(messages: tuple[BaseMessage, ...]) -> list[str]:
    snippets: list[str] = []
    for message in messages:
        if message.type not in {"human", "ai"}:
            continue
        text = _message_text(message)
        if not text:
            continue
        role = "user" if message.type == "human" else "assistant"
        snippets.append(f"- {role}: {text[:500]}")
        if len(snippets) >= 6:
            break
    return snippets


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return redact_text(" ".join(content.split())).text
    return redact_text(str(content)).text
