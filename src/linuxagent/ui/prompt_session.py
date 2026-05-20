"""Prompt-toolkit session management for the console UI."""

from __future__ import annotations

import os
from asyncio import Event
from collections.abc import AsyncGenerator, Callable, Iterable
from pathlib import Path
from typing import Any, cast

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.validation import ValidationError, Validator

from ..i18n import Translator, default_translator
from ..product_context import slash_commands

_DIRECT_COMMAND_PROMPT_STYLE = "ansibrightmagenta"


class PromptSessionManager:
    def __init__(
        self,
        *,
        theme: str,
        prompt_symbol: str,
        history_path: Path,
        session_factory: Any | None = None,
        translator: Translator | None = None,
    ) -> None:
        self._theme = theme
        self._prompt_symbol = prompt_symbol
        self._history_path = history_path
        self._translator = translator or default_translator()
        self._session_factory = session_factory or self._default_session_factory
        self._cancel_event: Event | None = None
        self._cancel_reason_setter: Callable[[str], None] | None = None

    def set_cancel_event(
        self, cancel_event: Event, reason_setter: Callable[[str], None] | None = None
    ) -> None:
        self._cancel_event = cancel_event
        self._cancel_reason_setter = reason_setter

    def create_session(self) -> Any:
        return self._session_factory()

    def dynamic_prompt(self, session: Any) -> Callable[[], list[tuple[str, str]]]:
        def prompt() -> list[tuple[str, str]]:
            return self.build_prompt(session.default_buffer.text)

        return prompt

    def build_prompt(self, current_text: str = "") -> list[tuple[str, str]]:
        accent = "ansiblue" if self._theme == "light" else "ansibrightcyan"
        symbol_style = "ansibrightblack"
        if current_text.startswith("!"):
            accent = _DIRECT_COMMAND_PROMPT_STYLE
            symbol_style = _DIRECT_COMMAND_PROMPT_STYLE
        return [
            (f"bold {accent}", "linuxagent"),
            ("", " "),
            (symbol_style, self._prompt_symbol),
            ("", " "),
        ]

    def _default_session_factory(self) -> PromptSession[str]:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._history_path.exists():
            fd = os.open(self._history_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        os.chmod(self._history_path, 0o600)
        os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")
        return PromptSession(
            history=FileHistory(str(self._history_path)),
            completer=cast(Completer, SlashCommandCompleter(self._translator)),
            validator=_NonEmptyInputValidator(),
            validate_while_typing=False,
            complete_while_typing=True,
            erase_when_done=True,
            reserve_space_for_menu=8,
            key_bindings=self._key_bindings(),
        )

    def _key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("escape", eager=True)  # type: ignore[misc]
        def _cancel_turn(_event: KeyPressEvent) -> None:
            if self._cancel_event is not None:
                if self._cancel_reason_setter is not None:
                    self._cancel_reason_setter("escape")
                self._cancel_event.set()

        return bindings


class SlashCommandCompleter:
    """Prompt-toolkit completer for slash commands."""

    def __init__(self, translator: Translator | None = None) -> None:
        self._translator = translator or default_translator()

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        del complete_event
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for item in slash_commands(self._translator):
            command = item.command
            description = item.description
            if command.startswith(text):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )

    async def get_completions_async(
        self, document: Document, complete_event: CompleteEvent
    ) -> AsyncGenerator[Completion, None]:
        for completion in self.get_completions(document, complete_event):
            yield completion


class _NonEmptyInputValidator(Validator):  # type: ignore[misc]
    def validate(self, document: Document) -> None:
        if document.text.strip():
            return
        raise ValidationError(cursor_position=0)
