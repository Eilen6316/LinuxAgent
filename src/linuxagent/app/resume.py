"""Resume-session rendering helpers."""

from __future__ import annotations

from typing import Any

from ..services import ChatSession


def resume_list(sessions: list[ChatSession]) -> str:
    if not sessions:
        return "没有可恢复的会话。"
    lines = ["可恢复会话："]
    for index, session in enumerate(sessions, start=1):
        lines.append(f"{index}. {session.title} ({len(session.messages)} messages)")
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
