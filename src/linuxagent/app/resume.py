"""Resume-session rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..i18n import Translator, default_translator
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


def resume_list(items: list[ResumeSessionItem], *, translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    if not items:
        return tr.t("resume.none")
    lines = [tr.t("resume.title")]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {resume_choice_label(item, translator=tr)}")
    lines.append(tr.t("resume.instruction"))
    return "\n".join(lines)


def render_resumed_session(session: ChatSession, *, translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    preview = _session_preview(list(session.messages), translator=tr)
    return tr.t("resume.restored", thread_id=session.thread_id, preview=preview)


def session_title(messages: list[Any]) -> str:
    for message in messages:
        if getattr(message, "type", "") == "human":
            text = " ".join(str(getattr(message, "content", "")).split())
            return text[:60] if text else default_translator().t("resume.untitled")
    return default_translator().t("resume.untitled")


def resume_choice_label(item: ResumeSessionItem, *, translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    prefix = f"[{item.status}] " if item.status else ""
    title = _compact(item.session.title, 48)
    updated = _time_label(item.session.updated_at)
    count = len(item.session.messages)
    message_count = tr.t("resume.choice_messages", count=count)
    return f"{prefix}{updated} {title}  · {message_count}"


def _session_preview(messages: list[Any], *, translator: Translator) -> str:
    tail = messages[-6:]
    lines: list[str] = []
    for message in tail:
        role = _display_role(str(getattr(message, "type", "message")), translator=translator)
        content = str(getattr(message, "content", "")).strip()
        lines.append(f"{role}:\n{content}")
    return "\n\n".join(lines)


def _display_role(role: str, *, translator: Translator) -> str:
    labels = {"human": translator.t("resume.role.human"), "ai": translator.t("resume.role.ai")}
    return labels.get(role, role)


def _compact(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}..."


def _time_label(value: datetime) -> str:
    local_value = value.astimezone()
    now = datetime.now().astimezone()
    if local_value.date() == now.date():
        return local_value.strftime("%H:%M")
    return local_value.strftime("%m-%d %H:%M")
