# mypy: disable-error-code=misc
"""Interactive resume session picker."""

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

MAX_VISIBLE_RESUME_ITEMS = 12


@dataclass
class ResumeSelector:
    """Prompt-toolkit selector that exits as soon as a session is chosen."""

    sessions: list[Any]
    max_visible: int = MAX_VISIBLE_RESUME_ITEMS

    def __post_init__(self) -> None:
        self._selected_index = 0
        self._top_index = 0

    async def choose(self) -> str | None:
        app: Application[str | None] = Application(
            layout=Layout(self._container()),
            mouse_support=True,
            full_screen=False,
            erase_when_done=True,
            style=_style(),
        )
        result = await app.run_async()
        return result if isinstance(result, str) or result is None else str(result)

    def move(self, delta: int) -> None:
        self._set_selected(self._selected_index + delta)

    def page(self, delta: int) -> None:
        self.move(delta * self._visible_count())

    def first(self) -> None:
        self._set_selected(0)

    def last(self) -> None:
        self._set_selected(len(self.sessions) - 1)

    def selected_thread_id(self) -> str | None:
        if not self.sessions:
            return None
        return str(getattr(self.sessions[self._selected_index], "thread_id", ""))

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

        @bindings.add("pageup")
        def _page_up(event: Any) -> None:
            del event
            self.page(-1)

        @bindings.add("pagedown")
        def _page_down(event: Any) -> None:
            del event
            self.page(1)

        @bindings.add("home")
        def _home(event: Any) -> None:
            del event
            self.first()

        @bindings.add("end")
        def _end(event: Any) -> None:
            del event
            self.last()

        @bindings.add("enter")
        def _enter(event: Any) -> None:
            event.app.exit(result=self.selected_thread_id())

        @bindings.add("escape")
        @bindings.add("q")
        @bindings.add("c-c")
        def _cancel(event: Any) -> None:
            event.app.exit(result=None)

        return bindings

    def _fragments(self) -> StyleAndTextTuples:
        result: StyleAndTextTuples = [
            ("class:title", "Resume session\n"),
            ("class:help", "Use Up/Down or mouse. Enter resumes. Esc cancels.\n"),
            ("", "\n"),
        ]
        for index, session in self._visible_sessions():
            selected = index == self._selected_index
            prefix = "❯ " if selected else "  "
            style = "class:selected" if selected else "class:item"
            result.append((style, prefix, self._mouse_handler(index)))
            result.append((style, _session_label(session), self._mouse_handler(index)))
            result.append(("", "\n"))
        result.extend(self._footer())
        return result

    def _footer(self) -> StyleAndTextTuples:
        if len(self.sessions) <= self._visible_count():
            return []
        start = self._top_index + 1
        end = min(self._top_index + self._visible_count(), len(self.sessions))
        return [
            ("", "\n"),
            ("class:help", f"Showing {start}-{end} of {len(self.sessions)} sessions"),
        ]

    def _visible_sessions(self) -> list[tuple[int, Any]]:
        end = min(self._top_index + self._visible_count(), len(self.sessions))
        return list(enumerate(self.sessions[self._top_index : end], self._top_index))

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
                get_app().exit(result=self.selected_thread_id())

        return handle

    def _set_selected(self, index: int) -> None:
        if not self.sessions:
            self._selected_index = 0
            self._top_index = 0
            return
        self._selected_index = min(max(index, 0), len(self.sessions) - 1)
        self._ensure_selected_visible()

    def _ensure_selected_visible(self) -> None:
        visible_count = self._visible_count()
        if self._selected_index < self._top_index:
            self._top_index = self._selected_index
        if self._selected_index >= self._top_index + visible_count:
            self._top_index = self._selected_index - visible_count + 1

    def _visible_count(self) -> int:
        return max(1, min(self.max_visible, len(self.sessions)))


def _style() -> Style:
    return Style.from_dict(
        {
            "title": "bold ansibrightcyan",
            "help": "ansibrightblack",
            "item": "",
            "selected": "reverse ansibrightcyan",
        }
    )


def _session_label(session: Any) -> str:
    label = getattr(session, "label", None)
    if isinstance(label, str) and label:
        return label
    title = str(getattr(session, "title", "Untitled session"))
    return title if title else "Untitled session"
