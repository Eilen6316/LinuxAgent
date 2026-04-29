"""Resume-session rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..services import ChatSession


@dataclass(frozen=True)
class ResumeSessionItem:
    session: ChatSession
    status: str = ""

    @property
    def thread_id(self) -> str:
        return self.session.thread_id

    @property
    def label(self) -> str:
        return resume_choice_label(self)


def resume_item(session: ChatSession, *, status: str = "") -> ResumeSessionItem:
    return ResumeSessionItem(session=session, status=status)


def resume_list(items: list[ResumeSessionItem]) -> str:
    if not items:
        return "没有可恢复的会话。"
    lines = ["可恢复会话："]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {resume_choice_label(item)}")
    lines.append("输入编号恢复会话；直接继续提问则保持当前新对话。")
    return "\n".join(lines)


def render_resumed_session(session: ChatSession) -> str:
    preview = _session_preview(list(session.messages))
    return f"已恢复会话 #{session.thread_id}：\n\n{preview}"


def session_title(messages: list[Any]) -> str:
    for message in messages:
        if getattr(message, "type", "") == "human":
            text = " ".join(str(getattr(message, "content", "")).split())
            return text[:60] if text else "Untitled session"
    return "Untitled session"


def resume_choice_label(item: ResumeSessionItem) -> str:
    prefix = f"[{item.status}] " if item.status else ""
    title = _compact(item.session.title, 48)
    updated = _time_label(item.session.updated_at)
    count = len(item.session.messages)
    return f"{prefix}{updated} {title}  · {count} messages"


def _session_preview(messages: list[Any]) -> str:
    tail = messages[-6:]
    lines: list[str] = []
    for message in tail:
        role = _display_role(str(getattr(message, "type", "message")))
        content = str(getattr(message, "content", "")).strip()
        lines.append(f"{role}:\n{content}")
    return "\n\n".join(lines)


def _display_role(role: str) -> str:
    return {"human": "你", "ai": "LinuxAgent"}.get(role, role)


def _compact(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}..."


def _time_label(value: datetime) -> str:
    local_value = value.astimezone()
    now = datetime.now().astimezone()
    if local_value.date() == now.date():
        return local_value.strftime("%H:%M")
    return local_value.strftime("%m-%d %H:%M")
