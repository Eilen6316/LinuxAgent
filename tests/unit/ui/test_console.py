"""Console UI tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from prompt_toolkit.document import Document
from rich.console import Console

from linuxagent.ui import ConsoleUI
from linuxagent.ui.console import SlashCommandCompleter


async def test_console_ui_non_tty_auto_denies(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    ui = ConsoleUI()
    result = await ui.handle_interrupt({"command": "ls -la"})
    assert result == {"decision": "non_tty_auto_deny", "latency_ms": 0}


class _FakeSession:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[object] = []
        self.default_buffer = SimpleNamespace(text="")

    async def prompt_async(self, prompt: Any) -> str:
        self.prompts.append(prompt() if callable(prompt) else prompt)
        if not self._responses:
            raise EOFError
        response = self._responses.pop(0)
        self.default_buffer.text = response
        return response


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


def test_console_prompt_turns_magenta_for_direct_shell_prefix() -> None:
    ui = ConsoleUI(prompt_symbol=">")

    normal = ui._build_prompt("status")
    direct = ui._build_prompt("!pwd")

    assert ("bold ansibrightmagenta", "linuxagent") not in normal
    assert ("bold ansibrightmagenta", "linuxagent") in direct
    assert ("ansibrightmagenta", ">") in direct


def test_slash_command_completer_suggests_commands() -> None:
    completer = SlashCommandCompleter()

    completions = list(completer.get_completions(Document("/h"), object()))

    assert [item.text for item in completions] == ["/help", "/history"]
    assert all(item.display_meta_text for item in completions)


async def test_slash_command_completer_supports_async_completion() -> None:
    completer = SlashCommandCompleter()

    completions = [item async for item in completer.get_completions_async(Document("/t"), object())]

    assert [item.text for item in completions] == ["/tools"]


def test_slash_command_completer_ignores_plain_text() -> None:
    completer = SlashCommandCompleter()

    assert list(completer.get_completions(Document("history"), object())) == []


def test_render_confirm_shows_basic_command_fields() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    ui._render_confirm(
        {
            "command": "ls -la",
            "goal": "List files",
            "purpose": "Inspect current directory",
            "safety_level": "CONFIRM",
            "matched_rule": "LLM_FIRST_RUN",
            "command_source": "llm",
            "risk_summary": "read-only",
            "preflight_checks": ["pwd"],
            "verification_commands": ["ls -la"],
        }
    )

    rendered = console.export_text()
    assert "Command" in rendered
    assert "ls -la" in rendered
    assert "LLM_FIRST_RUN" in rendered
    assert "read-only" in rendered


def test_render_file_patch_confirm_shows_planned_diff() -> None:
    console = Console(record=True, color_system="truecolor", width=120)
    ui = ConsoleUI(console=console)

    ui._render_file_patch_confirm(
        {
            "goal": "Edit demo",
            "files_changed": ["demo.sh"],
            "risk_summary": "writes one file",
            "risk_level": "high",
            "risk_reasons": ["path matches configured file_patch.high_risk_roots: demo.sh"],
            "high_risk_paths": ["demo.sh"],
            "permission_changes": [
                {"path": "demo.sh", "mode": "0755", "reason": "make executable"}
            ],
            "repair_attempt": 1,
            "verification_commands": ["sh demo.sh"],
            "unified_diff": "--- demo.sh\n+++ demo.sh\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        }
    )

    rendered = console.export_text()
    assert "Planned diff" in rendered
    assert "1 file, +1 -1" in rendered
    assert "Stats" in rendered
    assert "full diff shown" in rendered
    assert "repaired this diff (attempt 1)" in rendered
    assert "Elevated risk" in rendered
    assert "demo.sh -> 0755" in rendered
    assert "demo.sh" in rendered
    assert "-old" in rendered
    assert "+new" in rendered


def test_file_patch_approval_asks_each_file(monkeypatch) -> None:
    decisions = iter([True, False, True])
    asked: list[str] = []

    def fake_confirm(message: str, *, default: bool) -> bool:
        del default
        asked.append(message)
        return next(decisions)

    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", fake_confirm)
    ui = ConsoleUI()

    response = ui._approval_response(
        {"type": "confirm_file_patch", "files_changed": ["one.py", "two.py", "three.py"]}
    )

    assert response == {"decision": "yes", "selected_files": ["one.py", "three.py"]}
    assert asked == [
        "[bold]Apply one.py?[/]",
        "[bold]Apply two.py?[/]",
        "[bold]Apply three.py?[/]",
    ]


def test_file_patch_approval_applies_all_when_all_files_confirmed(monkeypatch) -> None:
    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", lambda message, *, default: True)
    ui = ConsoleUI()

    response = ui._approval_response(
        {"type": "confirm_file_patch", "files_changed": ["one.py", "two.py"]}
    )

    assert response == {"decision": "yes"}


def test_file_patch_approval_refuses_when_no_files_confirmed(monkeypatch) -> None:
    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", lambda message, *, default: False)
    ui = ConsoleUI()

    response = ui._approval_response(
        {"type": "confirm_file_patch", "files_changed": ["one.py", "two.py"]}
    )

    assert response == {"decision": "no"}


def test_render_confirm_shows_only_remaining_runbook_steps() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    ui._render_confirm(
        {
            "command": "du -sh /var/log",
            "runbook_id": "disk.full",
            "runbook_title": "Investigate disk usage",
            "runbook_step_index": 1,
            "runbook_steps": [
                {"command": "df -h", "purpose": "Show filesystem usage"},
                {"command": "du -sh /var/log", "purpose": "Estimate log directory usage"},
                {"command": "find /tmp -maxdepth 1", "purpose": "Inspect temp files"},
            ],
        }
    )

    rendered = console.export_text()
    assert "disk.full - Investigate disk usage" in rendered
    assert "Next steps" in rendered
    assert "find /tmp -maxdepth 1" in rendered
    assert "df -h - Show filesystem usage" not in rendered


def test_render_confirm_shows_batch_hosts() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    ui._render_confirm({"command": "uptime", "batch_hosts": ["web-1", "db-1"]})

    rendered = console.export_text()
    assert "Batch hosts" in rendered
    assert "web-1, db-1" in rendered


def test_render_confirm_shows_destructive_warning() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    ui._render_confirm({"command": "rm -rf /tmp/x", "is_destructive": True})

    rendered = console.export_text()
    assert "Destructive" in rendered
    assert "approval will not be whitelisted" in rendered


async def test_console_print_treats_model_output_as_plain_text() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    await ui.print("[bold]Rocky[/bold] **Linux**")

    rendered = console.export_text()
    assert "[bold]Rocky[/bold] **Linux**" in rendered
