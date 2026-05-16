"""Assistant response output helpers."""

from __future__ import annotations

from ..interfaces import UserInterface


async def print_assistant_response(ui: UserInterface, text: str) -> None:
    print_markdown = getattr(ui, "print_markdown", None)
    if callable(print_markdown):
        await print_markdown(text)
        return
    await ui.print(text)
