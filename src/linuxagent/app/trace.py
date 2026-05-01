"""Trace/activity slash command handling."""

from __future__ import annotations

from ..interfaces import UserInterface


async def handle_trace_command(ui: UserInterface, arg: str) -> None:
    normalized = arg.strip().casefold()
    if normalized in {"on", "show", "1", "true"}:
        ui.set_activity_visible(True)
        await ui.print("Trace/activity output is now visible.")
        return
    if normalized in {"off", "hide", "0", "false"}:
        ui.set_activity_visible(False)
        await ui.print("Trace/activity output is now hidden.")
        return
    await ui.print("用法：/trace on 或 /trace off")
