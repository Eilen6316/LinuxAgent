"""Bounded conversation context helper."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage


@dataclass
class ContextManager:
    max_items: int
    _items: list[BaseMessage] = field(default_factory=list)

    def add(self, messages: list[BaseMessage]) -> None:
        self._items.extend(messages)
        if len(self._items) > self.max_items:
            self._items = self._items[-self.max_items :]

    def snapshot(self) -> list[BaseMessage]:
        return list(self._items)

    def compact_text(self) -> str:
        return "\n".join(str(message.content) for message in self._items)
