"""Conversation history helper with secure local export."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict


@dataclass
class ChatService:
    history_path: Path
    max_messages: int
    _messages: list[BaseMessage] = field(default_factory=list)

    def add(self, messages: list[BaseMessage]) -> None:
        self._messages.extend(messages)
        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages :]

    def snapshot(self) -> list[BaseMessage]:
        return list(self._messages)

    def save(self) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            fd = os.open(self.history_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        os.chmod(self.history_path, 0o600)
        data = messages_to_dict(self._messages)
        self.history_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(self.history_path, 0o600)

    def load(self) -> None:
        if not self.history_path.is_file():
            return
        raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        self._messages = messages_from_dict(raw)[-self.max_messages :]

    def export_markdown(self) -> str:
        lines: list[str] = []
        for message in self._messages:
            role = message.type.title()
            lines.append(f"## {role}\n\n{message.content}\n")
        return "\n".join(lines).strip()
