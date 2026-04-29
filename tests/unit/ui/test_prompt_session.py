"""Prompt session manager tests."""

from __future__ import annotations

from types import SimpleNamespace

from prompt_toolkit.document import Document

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


def test_prompt_session_manager_default_history_file_is_0600(tmp_path) -> None:
    history_path = tmp_path / "prompt_history"
    manager = PromptSessionManager(
        theme="auto",
        prompt_symbol=">",
        history_path=history_path,
    )

    manager._default_session_factory()

    assert history_path.stat().st_mode & 0o777 == 0o600


def test_slash_command_completer_suggests_commands() -> None:
    completer = SlashCommandCompleter()

    completions = list(completer.get_completions(Document("/h"), object()))

    assert [item.text for item in completions] == ["/help", "/history"]
    assert all(item.display_meta_text for item in completions)
