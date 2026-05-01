# mypy: disable-error-code=misc
"""Interactive approval picker for HITL confirmations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style


@dataclass(frozen=True)
class ApprovalOption:
    key: str
    decision: str
    label: str
    description: str


@dataclass
class ApprovalSelector:
    options: tuple[ApprovalOption, ...]
    default_index: int | None = None

    def __post_init__(self) -> None:
        if not self.options:
            raise ValueError("approval selector requires at least one option")
        fallback_index = len(self.options) - 1
        index = fallback_index if self.default_index is None else self.default_index
        self._selected_index = min(max(index, 0), len(self.options) - 1)

    def choose(self) -> str:
        app: Application[str] = Application(
            layout=Layout(self._container()),
            mouse_support=True,
            full_screen=False,
            erase_when_done=True,
            style=_style(),
        )
        result = app.run(in_thread=True)
        return result if isinstance(result, str) else "no"

    def move(self, delta: int) -> None:
        self._set_selected(self._selected_index + delta)

    def selected_decision(self) -> str:
        return self.options[self._selected_index].decision

    def _container(self) -> HSplit:
        control = FormattedTextControl(
            self._fragments,
            focusable=True,
            key_bindings=self._key_bindings(),
            show_cursor=False,
        )
        return HSplit([Window(content=control, always_hide_cursor=True)])

    def _key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("up")
        @bindings.add("k")
        def _up(event: Any) -> None:
            del event
            self.move(-1)

        @bindings.add("down")
        @bindings.add("j")
        def _down(event: Any) -> None:
            del event
            self.move(1)

        @bindings.add("enter")
        def _enter(event: Any) -> None:
            event.app.exit(result=self.selected_decision())

        @bindings.add("escape")
        @bindings.add("q")
        @bindings.add("c-c")
        def _cancel(event: Any) -> None:
            event.app.exit(result="no")

        self._add_shortcut_bindings(bindings)
        return bindings

    def _add_shortcut_bindings(self, bindings: KeyBindings) -> None:
        shortcuts = {option.key: option.decision for option in self.options}
        shortcuts.update(
            {str(index): option.decision for index, option in enumerate(self.options, 1)}
        )
        for key, decision in shortcuts.items():

            @bindings.add(key)
            def _shortcut(event: Any, selected: str = decision) -> None:
                event.app.exit(result=selected)

    def _fragments(self) -> StyleAndTextTuples:
        result: StyleAndTextTuples = [
            ("class:title", "Allow this operation?\n"),
            ("class:help", "Use Up/Down or number keys. Enter selects. Esc refuses.\n"),
            ("", "\n"),
        ]
        for index, option in enumerate(self.options):
            selected = index == self._selected_index
            prefix = "❯ " if selected else "  "
            style = "class:selected" if selected else "class:item"
            result.append(
                (style, f"{prefix}{index + 1}. {option.label}\n", self._mouse_handler(index))
            )
            result.append(("class:help", f"    {option.description}\n", self._mouse_handler(index)))
        return result

    def _mouse_handler(self, index: int) -> Any:
        def handle(mouse_event: MouseEvent) -> None:
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                self.move(-1)
                get_app().invalidate()
                return
            if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                self.move(1)
                get_app().invalidate()
                return
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self._set_selected(index)
                get_app().invalidate()
                return
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self._set_selected(index)
                get_app().exit(result=self.selected_decision())

        return handle

    def _set_selected(self, index: int) -> None:
        self._selected_index = min(max(index, 0), len(self.options) - 1)


def _style() -> Style:
    return Style.from_dict(
        {
            "title": "bold ansibrightcyan",
            "help": "ansibrightblack",
            "item": "",
            "selected": "reverse ansibrightcyan",
        }
    )
