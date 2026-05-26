"""Slash command helpers for local advisory memory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config.models import MemoryConfig
from ..i18n import Translator, default_translator
from ..interfaces import UserInterface
from ..memory import (
    MemoryDisabledError,
    MemoryStore,
    format_memory_notes,
    format_memory_status,
    format_memory_suggestions,
)
from ..memory.suggestions import suggest_from_history

if TYPE_CHECKING:
    from ..services import ChatService
    from .agent import LinuxAgent


def agent_memory_store(agent: LinuxAgent) -> MemoryStore:
    if agent.memory_store is None:
        agent.memory_store = MemoryStore(MemoryConfig())
    return agent.memory_store


async def handle_memory_command(
    ui: UserInterface,
    memory_store: MemoryStore,
    arg: str,
    *,
    chat_service: ChatService | None = None,
    translator: Translator | None = None,
) -> None:
    tr = translator or default_translator()
    command, _, rest = arg.strip().partition(" ")
    match command or "status":
        case "status":
            await ui.print(format_memory_status(memory_store.status(), translator=tr))
        case "list":
            await ui.print(format_memory_notes(memory_store.list_notes(), translator=tr))
        case "pending":
            await ui.print(
                format_memory_suggestions(memory_store.list_suggestions(), translator=tr)
            )
        case "summary":
            summary = memory_store.read_summary().strip()
            await ui.print(summary or tr.t("memory.summary_empty"))
        case "add":
            text = rest.strip()
            if not text:
                await ui.print(tr.t("memory.add_usage"))
                return
            try:
                note = memory_store.add_note(text)
            except MemoryDisabledError:
                await ui.print(tr.t("memory.disabled", path=memory_store.root))
                return
            except ValueError as exc:
                await ui.print(tr.t("memory.error", message=exc))
                return
            await ui.print(tr.t("memory.added", path=note.path))
        case "suggest":
            if chat_service is None:
                await ui.print(tr.t("memory.suggest_unavailable"))
                return
            try:
                chat_service.load()
                result = suggest_from_history(memory_store, chat_service)
            except MemoryDisabledError:
                await ui.print(tr.t("memory.disabled", path=memory_store.root))
                return
            except ValueError as exc:
                await ui.print(tr.t("memory.error", message=exc))
                return
            if result.suggestion is None:
                await ui.print(tr.t("memory.suggest_none"))
                return
            await ui.print(
                tr.t("memory.suggested", path=result.suggestion.path, sessions=result.session_count)
            )
        case "promote":
            name = rest.strip()
            if not name:
                await ui.print(tr.t("memory.promote_usage"))
                return
            try:
                note = memory_store.promote_suggestion(name)
            except MemoryDisabledError:
                await ui.print(tr.t("memory.disabled", path=memory_store.root))
                return
            except (FileNotFoundError, ValueError) as exc:
                await ui.print(tr.t("memory.error", message=exc))
                return
            await ui.print(tr.t("memory.promoted", path=note.path))
        case _:
            await ui.print(tr.t("memory.usage"))
