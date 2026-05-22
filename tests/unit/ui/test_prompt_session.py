"""Prompt session manager tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from prompt_toolkit.document import Document
from prompt_toolkit.keys import Keys
from prompt_toolkit.validation import ValidationError

from linuxagent.ui.prompt_session import PromptSessionManager, SlashCommandCompleter


def test_prompt_session_manager_builds_dynamic_prompt(tmp_path) -> None:
    manager = PromptSessionManager(
        theme="auto",
        prompt_symbol=">",
        history_path=tmp_path / "history",
        session_factory=lambda: SimpleNamespace(default_buffer=SimpleNamespace(text="!pwd")),
    )

    session = manager.create_session()
    prompt = manager.dynamic_prompt(session)

    assert ("bold ansibrightmagenta", "linuxagent") in prompt()
    assert ("ansibrightmagenta", ">") in prompt()


def test_prompt_session_manager_keeps_prompt_visible_while_activity_busy(tmp_path) -> None:
    invalidations = 0

    class _FakeApp:
        def invalidate(self) -> None:
            nonlocal invalidations
            invalidations += 1

    manager = PromptSessionManager(
        theme="auto",
        prompt_symbol=">",
        history_path=tmp_path / "history",
        session_factory=lambda: SimpleNamespace(
            default_buffer=SimpleNamespace(text="status"),
            app=_FakeApp(),
        ),
    )

    session = manager.create_session()
    prompt = manager.dynamic_prompt(session)
    manager.set_activity_busy(True)

    assert ("bold ansibrightcyan", "linuxagent") in prompt()
    assert ("ansibrightblack", ">") in prompt()
    assert invalidations == 1

    manager.set_activity_busy(False)

    assert ("bold ansibrightcyan", "linuxagent") in prompt()
    assert invalidations == 2


def test_prompt_session_manager_default_history_file_is_0600(tmp_path) -> None:
    history_path = tmp_path / "prompt_history"
    manager = PromptSessionManager(
        theme="auto",
        prompt_symbol=">",
        history_path=history_path,
    )

    session = manager._default_session_factory()

    assert history_path.stat().st_mode & 0o777 == 0o600
    assert session.app.erase_when_done is True


def test_prompt_session_manager_rejects_empty_input(tmp_path) -> None:
    manager = PromptSessionManager(
        theme="auto",
        prompt_symbol=">",
        history_path=tmp_path / "history",
    )

    session = manager._default_session_factory()

    with pytest.raises(ValidationError):
        session.validator.validate(Document(""))


async def test_prompt_session_escape_sets_cancel_event(tmp_path) -> None:
    cancel_event = asyncio.Event()
    reasons: list[str] = []
    manager = PromptSessionManager(
        theme="auto",
        prompt_symbol=">",
        history_path=tmp_path / "history",
    )
    manager.set_cancel_event(cancel_event, reasons.append)

    bindings = manager._key_bindings().get_bindings_for_keys((Keys.Escape,))
    assert bindings
    bindings[-1].handler(object())

    assert cancel_event.is_set()
    assert reasons == ["escape"]


def test_slash_command_completer_suggests_commands() -> None:
    completer = SlashCommandCompleter()

    completions = list(completer.get_completions(Document("/h"), object()))

    assert [item.text for item in completions] == ["/help"]
    assert all(item.display_meta_text for item in completions)

    resume = list(completer.get_completions(Document("/r"), object()))
    assert [item.text for item in resume] == ["/resume"]
