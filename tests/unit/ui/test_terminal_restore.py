"""Terminal restore helper tests."""

from __future__ import annotations

import termios
from contextlib import suppress

from linuxagent.ui import terminal_restore


async def test_run_with_terminal_restore_restores_attrs(monkeypatch) -> None:
    calls: list[object] = []
    attrs = ["before"]

    monkeypatch.setattr(terminal_restore.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(terminal_restore.sys.stdin, "fileno", lambda: 0)
    monkeypatch.setattr(termios, "tcgetattr", lambda _fd: attrs)
    monkeypatch.setattr(termios, "tcsetattr", lambda *_args: calls.append(_args))

    async def action() -> str:
        return "ok"

    assert await terminal_restore.run_with_terminal_restore(action) == "ok"
    assert calls == [(0, termios.TCSADRAIN, attrs)]


async def test_run_with_terminal_restore_restores_after_error(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(terminal_restore.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(terminal_restore.sys.stdin, "fileno", lambda: 0)
    monkeypatch.setattr(termios, "tcgetattr", lambda _fd: ["before"])
    monkeypatch.setattr(termios, "tcsetattr", lambda *_args: calls.append(_args))

    async def action() -> str:
        raise RuntimeError("boom")

    with suppress(RuntimeError):
        await terminal_restore.run_with_terminal_restore(action)

    assert len(calls) == 1
