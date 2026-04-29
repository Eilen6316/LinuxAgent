"""Prompt-toolkit session management for the console UI."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable, Iterable
from pathlib import Path
from typing import Any, cast

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory

_SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/help", "Show available slash commands"),
    ("/resume", "List saved sessions, then choose one to resume"),
    ("/new", "Start a fresh empty-context conversation"),
    ("/clear", "Alias for /new"),
    ("/tools", "Show enabled local/LLM tool entry points"),
    ("/exit", "Exit LinuxAgent"),
    ("/quit", "Alias for /exit"),
    ("!", "Run a shell command directly and add output to context"),
)

_DIRECT_COMMAND_PROMPT_STYLE = "ansibrightmagenta"


class PromptSessionManager:
    def __init__(
        self,
        *,
        theme: str,
        prompt_symbol: str,
        history_path: Path,
        session_factory: Any | None = None,
    ) -> None:
        self._theme = theme
        self._prompt_symbol = prompt_symbol
        self._history_path = history_path
        self._session_factory = session_factory or self._default_session_factory

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
        return PromptSession(
            history=FileHistory(str(self._history_path)),
            completer=cast(Completer, SlashCommandCompleter()),
            complete_while_typing=True,
            reserve_space_for_menu=8,
        )


class SlashCommandCompleter:
    """Prompt-toolkit completer for slash commands."""

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        del complete_event
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for command, description in _SLASH_COMMANDS:
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
