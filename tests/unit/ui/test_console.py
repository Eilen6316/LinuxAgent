"""Console UI tests."""

from __future__ import annotations

import sys

from linuxagent.ui import ConsoleUI


async def test_console_ui_non_tty_auto_denies(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    ui = ConsoleUI()
    result = await ui.handle_interrupt({"command": "ls -la"})
    assert result == {"decision": "non_tty_auto_deny", "latency_ms": 0}
