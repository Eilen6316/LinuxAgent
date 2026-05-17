"""Trace/activity slash command handling."""

from __future__ import annotations

from ..i18n import Translator, default_translator
from ..interfaces import UserInterface


async def handle_trace_command(
    ui: UserInterface,
    arg: str,
    *,
    translator: Translator | None = None,
) -> None:
    tr = translator or default_translator()
    normalized = arg.strip().casefold()
    if normalized in {"on", "show", "1", "true"}:
        ui.set_activity_visible(True)
        await ui.print(tr.t("trace.visible"))
        return
    if normalized in {"off", "hide", "0", "false"}:
        ui.set_activity_visible(False)
        await ui.print(tr.t("trace.hidden"))
        return
    await ui.print(tr.t("trace.usage"))
