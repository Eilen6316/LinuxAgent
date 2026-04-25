"""Console UI tests."""

from __future__ import annotations

import sys
from pathlib import Path

from linuxagent.ui import ConsoleUI


async def test_console_ui_non_tty_auto_denies(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    ui = ConsoleUI()
    result = await ui.handle_interrupt({"command": "ls -la"})
    assert result == {"decision": "non_tty_auto_deny", "latency_ms": 0}


class _FakeSession:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[object] = []

    async def prompt_async(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise EOFError
        return self._responses.pop(0)


async def test_console_ui_input_stream_uses_prompt_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    session = _FakeSession(["", "status", ""])
    ui = ConsoleUI(
        history_path=tmp_path / "prompt_history",
        session_factory=lambda: session,
        prompt_symbol=">",
    )

    items = []
    async for item in ui.input_stream():
        items.append(item)

    assert items == ["status"]
    assert "linuxagent" in str(session.prompts[0])


def test_console_ui_default_history_file_is_0600(tmp_path: Path) -> None:
    history_path = tmp_path / "prompt_history"
    ui = ConsoleUI(history_path=history_path)

    ui._default_session_factory()

    assert history_path.stat().st_mode & 0o777 == 0o600
