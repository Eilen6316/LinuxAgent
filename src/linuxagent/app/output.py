"""Assistant response output helpers."""

from __future__ import annotations

from ..interfaces import UserInterface


def start_working(ui: UserInterface) -> None:
    start = getattr(ui, "start_working", None)
    if callable(start):
        start()


async def print_user_input(ui: UserInterface, text: str) -> None:
    printer = getattr(ui, "print_user_input", None)
    if callable(printer):
        await printer(text)
        return
    await ui.print(text)


async def update_pending_inputs(ui: UserInterface, inputs: tuple[str, ...] | str | None) -> None:
    updater = getattr(ui, "update_pending_inputs", None)
    if callable(updater):
        pending = () if inputs is None else (inputs,) if isinstance(inputs, str) else inputs
        await updater(pending)


async def print_assistant_response(ui: UserInterface, text: str) -> None:
    print_markdown = getattr(ui, "print_markdown", None)
    if callable(print_markdown):
        await print_markdown(text)
        return
    await ui.print(text)
