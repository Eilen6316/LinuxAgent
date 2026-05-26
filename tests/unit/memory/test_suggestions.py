"""Pending memory suggestion tests."""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from linuxagent.config.models import MemoryConfig
from linuxagent.memory import MemoryStore
from linuxagent.memory.suggestions import suggest_from_history
from linuxagent.services import ChatService


def test_suggest_from_history_writes_pending_redacted_candidate(tmp_path: Path) -> None:
    chat = ChatService(tmp_path / "history.json", max_messages=10)
    chat.replace_session(
        "thread-1",
        [
            HumanMessage(content="Remember token=abc123 for this project"),
            AIMessage(content="Use journalctl before tailing logs."),
        ],
        title="Project preference",
    )
    chat.save()
    loaded = ChatService(tmp_path / "history.json", max_messages=10)
    loaded.load()
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))

    result = suggest_from_history(store, loaded, session_limit=3)

    assert result.session_count == 1
    assert result.suggestion is not None
    text = result.suggestion.path.read_text(encoding="utf-8")
    assert result.suggestion.path.parent == store.pending_dir
    assert "Review this pending memory before promotion" in text
    assert "Project preference" in text
    assert "token=***redacted***" in text
    assert "abc123" not in text
    assert store.list_notes() == ()


def test_suggest_from_history_returns_none_without_sessions(tmp_path: Path) -> None:
    chat = ChatService(tmp_path / "history.json", max_messages=10)
    store = MemoryStore(MemoryConfig(enabled=True, path=tmp_path / "memories"))

    result = suggest_from_history(store, chat)

    assert result.suggestion is None
    assert result.session_count == 0
