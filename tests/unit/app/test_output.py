"""Assistant output helper tests."""

from __future__ import annotations

from linuxagent.app.output import print_assistant_response, start_working


class _MarkdownUI:
    def __init__(self) -> None:
        self.plain: list[str] = []
        self.markdown: list[str] = []

    async def print(self, text: str) -> None:
        self.plain.append(text)

    async def print_markdown(self, text: str) -> None:
        self.markdown.append(text)


class _PlainUI:
    def __init__(self) -> None:
        self.plain: list[str] = []

    async def print(self, text: str) -> None:
        self.plain.append(text)


class _WorkingUI:
    def __init__(self) -> None:
        self.started = 0

    def start_working(self) -> None:
        self.started += 1


def test_start_working_uses_optional_ui_capability() -> None:
    ui = _WorkingUI()

    start_working(ui)  # type: ignore[arg-type]

    assert ui.started == 1


def test_start_working_ignores_plain_ui() -> None:
    start_working(_PlainUI())  # type: ignore[arg-type]


async def test_print_assistant_response_prefers_markdown_ui() -> None:
    ui = _MarkdownUI()

    await print_assistant_response(ui, "**ok**")  # type: ignore[arg-type]

    assert ui.markdown == ["**ok**"]
    assert ui.plain == []


async def test_print_assistant_response_falls_back_to_plain_ui() -> None:
    ui = _PlainUI()

    await print_assistant_response(ui, "**ok**")  # type: ignore[arg-type]

    assert ui.plain == ["**ok**"]
