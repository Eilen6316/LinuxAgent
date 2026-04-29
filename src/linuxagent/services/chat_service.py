"""Conversation history helper with secure local export."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

DEFAULT_SESSION_ID = "default"


@dataclass(frozen=True)
class ChatSession:
    thread_id: str
    title: str
    messages: tuple[BaseMessage, ...]
    created_at: datetime
    updated_at: datetime


@dataclass
class ChatService:
    history_path: Path
    max_messages: int
    _messages: list[BaseMessage] = field(default_factory=list)
    _sessions: dict[str, ChatSession] = field(default_factory=dict)

    def add(self, messages: list[BaseMessage]) -> None:
        self.replace_session(DEFAULT_SESSION_ID, [*self._messages, *messages])

    def replace(self, messages: list[BaseMessage]) -> None:
        self.replace_session(DEFAULT_SESSION_ID, messages)

    def snapshot(self, thread_id: str | None = None) -> list[BaseMessage]:
        if thread_id is None:
            return list(self._messages)
        session = self._sessions.get(thread_id)
        return [] if session is None else list(session.messages)

    def replace_session(
        self,
        thread_id: str,
        messages: list[BaseMessage],
        *,
        title: str | None = None,
    ) -> None:
        trimmed = list(messages[-self.max_messages :])
        now = _now()
        existing = self._sessions.get(thread_id)
        self._sessions[thread_id] = ChatSession(
            thread_id=thread_id,
            title=title or _session_title(trimmed),
            messages=tuple(trimmed),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self._messages = trimmed

    def list_sessions(self, *, limit: int = 10) -> list[ChatSession]:
        sessions = sorted(self._sessions.values(), key=lambda session: session.updated_at)
        return list(reversed(sessions[-limit:]))

    def get_session(self, thread_id: str) -> ChatSession | None:
        return self._sessions.get(thread_id)

    def save(self) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            fd = os.open(self.history_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        os.chmod(self.history_path, 0o600)
        data = {
            "version": 2,
            "sessions": [
                {
                    "thread_id": session.thread_id,
                    "title": session.title,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "messages": messages_to_dict(list(session.messages)),
                }
                for session in self._sessions.values()
            ],
        }
        self.history_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.chmod(self.history_path, 0o600)

    def load(self) -> None:
        if not self.history_path.is_file():
            return
        raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            self.replace(messages_from_dict(raw))
            return
        if isinstance(raw, dict):
            self._load_sessions(raw.get("sessions"))

    def export_markdown(self) -> str:
        lines: list[str] = []
        for message in self._messages:
            role = message.type.title()
            lines.append(f"## {role}\n\n{message.content}\n")
        return "\n".join(lines).strip()

    def _load_sessions(self, raw_sessions: Any) -> None:
        if not isinstance(raw_sessions, list):
            return
        self._sessions.clear()
        self._messages = []
        fallback_time = _now()
        for index, raw_session in enumerate(raw_sessions):
            if isinstance(raw_session, dict):
                self._load_session(raw_session, fallback_time + timedelta(microseconds=index))

    def _load_session(self, raw_session: dict[str, Any], fallback_time: datetime) -> None:
        raw_thread_id = raw_session.get("thread_id")
        raw_messages = raw_session.get("messages")
        if not isinstance(raw_thread_id, str) or not isinstance(raw_messages, list):
            return
        messages = messages_from_dict(raw_messages)
        raw_title = raw_session.get("title")
        trimmed = list(messages[-self.max_messages :])
        created_at = _parse_time(raw_session.get("created_at")) or fallback_time
        updated_at = _parse_time(raw_session.get("updated_at")) or created_at
        self._sessions[raw_thread_id] = ChatSession(
            thread_id=raw_thread_id,
            title=raw_title if isinstance(raw_title, str) else _session_title(trimmed),
            messages=tuple(trimmed),
            created_at=created_at,
            updated_at=updated_at,
        )
        self._messages = trimmed


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _session_title(messages: list[BaseMessage]) -> str:
    for message in messages:
        if message.type == "human":
            text = " ".join(str(message.content).split())
            return text[:60] if text else "Untitled session"
    return "Untitled session"
