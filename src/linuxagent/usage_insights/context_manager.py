"""Bounded conversation context helper."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage

_SUMMARY_PREFIX = "[summary]"


@dataclass
class ContextManager:
    max_items: int
    _items: list[BaseMessage] = field(default_factory=list)

    def replace(self, messages: list[BaseMessage]) -> None:
        self._items = list(messages)
        self._compress()

    def add(self, messages: list[BaseMessage]) -> None:
        self._items.extend(messages)
        self._compress()

    def snapshot(self) -> list[BaseMessage]:
        return list(self._items)

    def compact_text(self) -> str:
        return "\n".join(str(message.content) for message in self._items)

    def _compress(self) -> None:
        if self.max_items < 1:
            self._items = []
            return
        if len(self._items) <= self.max_items:
            return

        tail_size = max(self.max_items - 1, 0)
        older = self._items[:-tail_size] if tail_size else list(self._items)
        recent = self._items[-tail_size:] if tail_size else []
        summary = AIMessage(content=_summarize_messages(older))
        self._items = [summary, *recent]


def _summarize_messages(messages: list[BaseMessage]) -> str:
    lines = [_SUMMARY_PREFIX]
    for message in messages:
        role = message.type.upper()
        content = " ".join(str(message.content).split())
        if len(content) > 120:
            content = f"{content[:117]}..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)
