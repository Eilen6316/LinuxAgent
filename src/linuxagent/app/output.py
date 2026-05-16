"""Assistant response output helpers."""

from __future__ import annotations

from ..interfaces import UserInterface


def start_working(ui: UserInterface) -> None:
    start = getattr(ui, "start_working", None)
    if callable(start):
        start()


async def print_assistant_response(ui: UserInterface, text: str) -> None:
    print_markdown = getattr(ui, "print_markdown", None)
    if callable(print_markdown):
        await print_markdown(text)
        return
    await ui.print(text)
