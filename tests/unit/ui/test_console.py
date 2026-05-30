"""Console UI tests."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from prompt_toolkit.document import Document
from rich.console import Console

import linuxagent.ui.console as console_module
from linuxagent import __version__
from linuxagent.active_view import (
    ActivePlanItemView,
    ActiveTokenUsageView,
    ActiveTurnView,
    ActiveWorkItemView,
)
from linuxagent.config.models import LanguageCode
from linuxagent.i18n import Translator
from linuxagent.interfaces import ExecutionResult
from linuxagent.ui import ConsoleUI
from linuxagent.ui import working_status as working_status_module
from linuxagent.ui.console import SlashCommandCompleter
from linuxagent.ui.working_status import WorkingStatus, _plan_item_marker

EN_TRANSLATOR = Translator(LanguageCode.EN_US)


def _english_console_ui(console: Console | None = None) -> ConsoleUI:
    return ConsoleUI(console=console, translator=EN_TRANSLATOR)


def _render_working_status(ui: ConsoleUI, *, width: int) -> str:
    assert ui._working_status is not None
    render_console = Console(record=True, width=width)
    render_console.print(ui._working_status._render())
    return render_console.export_text()


def _rule_lines(rendered: str) -> list[str]:
    rule = "─" * 72
    return [line for line in rendered.splitlines() if rule in line]


async def test_console_ui_non_tty_auto_denies(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    ui = ConsoleUI()
    result = await ui.handle_interrupt({"command": "ls -la"})
    assert result == {"decision": "non_tty_auto_deny", "latency_ms": 0}


def test_console_ui_reports_interactive_only_with_tty_terminal(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert ConsoleUI(console=Console(force_terminal=True)).is_interactive() is True
    assert ConsoleUI(console=Console(record=True)).is_interactive() is False


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


async def test_console_ui_input_stream_patches_stdout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    session = _FakeSession(["status", ""])
    ui = ConsoleUI(
        history_path=tmp_path / "prompt_history",
        session_factory=lambda: session,
    )
    captured: list[bool] = []

    class _PatchStdout:
        def __init__(self, *, raw: bool) -> None:
            self._raw = raw

        def __enter__(self) -> None:
            captured.append(self._raw)
            return None

        def __exit__(self, exc_type, exc, tb) -> bool:
            del exc_type, exc, tb
            return False

    monkeypatch.setattr(console_module, "patch_stdout", lambda raw=False: _PatchStdout(raw=raw))

    items = []
    async for item in ui.input_stream():
        items.append(item)

    assert items == ["status"]
    assert captured
    assert all(captured)


async def test_console_print_user_input_follows_current_stdout(monkeypatch) -> None:
    console = Console(record=True, width=40)
    ui = _english_console_ui(console)
    original_file = console._file
    redirected = io.StringIO()

    monkeypatch.setattr(sys, "stdout", redirected)

    await ui.print_user_input("hello")

    assert "hello" in redirected.getvalue()
    assert console._file is original_file


async def test_wait_for_cancel_uses_prompt_cancel_event(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    ui = ConsoleUI(console=Console(force_terminal=True))

    task = asyncio.create_task(ui.wait_for_cancel())
    await asyncio.sleep(0)
    ui._cancel_event.set()

    assert await asyncio.wait_for(task, timeout=0.1) == "escape"


async def test_wait_for_cancel_can_yield_for_pending_input(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    ui = ConsoleUI(console=Console(force_terminal=True))
    await ui.update_pending_inputs(("next question",))

    task = asyncio.create_task(ui.wait_for_cancel())
    await asyncio.sleep(0)

    assert ui.request_pending_input_interrupt() is True
    assert await asyncio.wait_for(task, timeout=0.1) == "pending_input"


def test_console_ui_prints_linuxagent_wordmark() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

    ui._print_hero()

    rendered = console.export_text()
    assert "████" in rendered
    assert "HITL-safe" not in rendered
    assert "▟▙" not in rendered
    assert "╭" not in rendered
    assert "LLM-driven Linux operations" in rendered
    assert "Human-in-the-Loop safety" in rendered
    assert f"v{__version__}" in rendered
    assert "/help" in rendered
    assert "─" in rendered


def test_console_ui_hero_meta_includes_provider_and_model() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(
        console=console,
        translator=EN_TRANSLATOR,
        provider="anthropic",
        model="claude-sonnet-4-6",
    )

    ui._print_hero()

    rendered = console.export_text()
    assert "anthropic/claude-sonnet-4-6" in rendered
    assert f"v{__version__}" in rendered


def test_console_ui_uses_compact_wordmark_on_narrow_terminals() -> None:
    console = Console(record=True, width=40)
    ui = _english_console_ui(console)

    ui._print_hero()

    rendered = console.export_text()
    assert "LINUXAGENT" in rendered
    assert f"v{__version__}" in rendered
    assert "LLM-driven" not in rendered


def test_console_ui_default_history_file_is_0600(tmp_path: Path) -> None:
    history_path = tmp_path / "prompt_history"
    ui = ConsoleUI(history_path=history_path)

    ui._default_session_factory()

    assert history_path.stat().st_mode & 0o777 == 0o600


def test_console_ui_disables_prompt_toolkit_cpr(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PROMPT_TOOLKIT_NO_CPR", raising=False)
    ui = ConsoleUI(history_path=tmp_path / "prompt_history")

    ui._default_session_factory()

    assert os.environ["PROMPT_TOOLKIT_NO_CPR"] == "1"


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

    assert [item.text for item in completions] == ["/help"]
    resume = list(completer.get_completions(Document("/r"), object()))
    assert [item.text for item in resume] == ["/resume"]
    assert all(item.display_meta_text for item in completions)


async def test_slash_command_completer_supports_async_completion() -> None:
    completer = SlashCommandCompleter()

    completions = [item async for item in completer.get_completions_async(Document("/t"), object())]

    assert [item.text for item in completions] == ["/tools", "/trace"]


def test_slash_command_completer_ignores_plain_text() -> None:
    completer = SlashCommandCompleter()

    assert list(completer.get_completions(Document("history"), object())) == []


def test_render_confirm_shows_basic_command_fields() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

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
            "sandbox_preview": {
                "requested_profile": "system_inspect",
                "runner": "noop",
                "enabled": False,
                "enforced": False,
                "runtime_label": "no_isolation",
                "network": "inherit",
                "cwd": str(Path.cwd()),
                "allowed_roots": [str(Path.cwd())],
                "fallback_reason": "sandbox disabled",
            },
        }
    )

    rendered = console.export_text()
    assert "Command" in rendered
    assert "ls -la" in rendered
    assert "LLM_FIRST_RUN" in rendered
    assert "read-only" in rendered
    assert "profile=system_inspect" in rendered
    assert "runner=noop" in rendered
    assert "runtime=no_isolation" in rendered
    assert "no sandbox isolation" in rendered
    assert "sandbox disabled" in rendered


def test_render_confirm_shows_policy_details_and_whitelist_block() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

    ui._render_confirm(
        {
            "type": "confirm_command",
            "command": "python3 -c 'print(1)'",
            "safety_level": "CONFIRM",
            "matched_rule": "LLM_FIRST_RUN",
            "matched_rules": ["LLM_FIRST_RUN", "LOLBIN_PYTHON3_EXEC"],
            "command_source": "llm",
            "risk_score": 90,
            "capabilities": ["llm.generated", "interpreter.escape"],
            "risk_details": {"reason": "LLM-generated command; python3 inline code execution"},
            "can_whitelist": False,
        }
    )

    rendered = console.export_text()
    assert "LOLBIN_PYTHON3_EXEC" in rendered
    assert "interpreter.escape" in rendered
    assert "Policy risk" in rendered
    assert "high - interpreter or LOLBin execution requires careful operator review" in rendered
    assert "not allowed - policy requires confirmation every time" in rendered


def test_render_confirm_shows_inline_payload_with_line_numbers() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

    ui._render_confirm(
        {
            "type": "confirm_command",
            "command": "python3 -c 'print(1)'",
            "safety_level": "CONFIRM",
            "matched_rules": ["LOLBIN_PYTHON3_EXEC"],
            "capabilities": ["interpreter.escape"],
        }
    )

    rendered = console.export_text()
    assert "Inline payload (python3 -c)" in rendered
    assert "1 | print(1)" in rendered


def test_render_confirm_marks_truncated_command_and_inline_payload() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)
    payload = "print(" + repr("x" * 2000) + ")"

    ui._render_confirm(
        {
            "type": "confirm_command",
            "command": f"python3 -c {payload!r}",
            "safety_level": "CONFIRM",
            "matched_rules": ["LOLBIN_PYTHON3_EXEC"],
            "capabilities": ["interpreter.escape"],
        }
    )

    rendered = console.export_text()
    assert "Command note" in rendered
    assert "Inline note" in rendered
    assert "truncated for review; audit keeps the full command" in rendered


def test_render_file_patch_confirm_shows_planned_diff() -> None:
    console = Console(record=True, color_system="truecolor", width=120)
    ui = _english_console_ui(console)

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
    assert "Edited demo.sh (+1 -1)" in rendered
    assert "1 -old" in rendered
    assert "1 +new" in rendered


def test_render_file_patch_confirm_default_locale_is_chinese() -> None:
    console = Console(record=True, color_system="truecolor", width=120)
    ui = ConsoleUI(console=console)

    ui._render_file_patch_confirm(
        {
            "goal": "Edit demo",
            "files_changed": ["demo.sh"],
            "unified_diff": "--- demo.sh\n+++ demo.sh\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        }
    )

    rendered = console.export_text()
    assert "计划 diff" in rendered
    assert "修改 demo.sh (+1 -1)" in rendered


def test_file_patch_approval_asks_each_file(monkeypatch) -> None:
    decisions = iter([True, False, True])
    asked: list[str] = []

    def fake_confirm(message: str, *, default: bool) -> bool:
        del default
        asked.append(message)
        return next(decisions)

    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", fake_confirm)
    ui = _english_console_ui()

    response = ui._approval_response(
        {
            "type": "confirm_file_patch",
            "files_changed": ["one.py", "two.py", "three.py"],
            "unified_diff": "\n".join(
                [
                    "--- one.py",
                    "+++ one.py",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                    "--- two.py",
                    "+++ two.py",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                    "--- three.py",
                    "+++ three.py",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                ]
            ),
        }
    )

    assert response == {"decision": "yes", "selected_files": ["one.py", "three.py"]}
    assert asked == [
        "[bold]Apply one.py?[/]",
        "[bold]Apply two.py?[/]",
        "[bold]Apply three.py?[/]",
    ]


def test_file_patch_approval_pages_expanded_large_diff(monkeypatch) -> None:
    decisions = iter([True, False])

    def fake_confirm(message: str, *, default: bool) -> bool:
        del message, default
        return next(decisions)

    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", fake_confirm)
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)
    body = "\n".join(f"+line {index}" for index in range(250))

    response = ui._approval_response(
        {
            "type": "confirm_file_patch",
            "files_changed": ["demo.py"],
            "unified_diff": f"--- /dev/null\n+++ demo.py\n@@ -0,0 +250 @@\n{body}\n",
        }
    )

    assert response == {"decision": "no"}
    rendered = console.export_text()
    assert "Created demo.py (+250 -0)" in rendered
    assert "page 2/2" in rendered


def test_file_patch_approval_does_not_reexpand_full_diff(monkeypatch) -> None:
    asked: list[str] = []

    def fake_confirm(message: str, *, default: bool) -> bool:
        del default
        asked.append(message)
        return True

    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", fake_confirm)
    ui = _english_console_ui()

    response = ui._approval_response(
        {
            "type": "confirm_file_patch",
            "files_changed": ["demo.py"],
            "unified_diff": "--- demo.py\n+++ demo.py\n@@ -1 +1 @@\n-old\n+new\n",
        }
    )

    assert response == {"decision": "yes"}
    assert asked == ["[bold]Allow this operation?[/]"]


def test_command_approval_can_allow_all_in_conversation(monkeypatch) -> None:
    seen_options: list[tuple[str, str]] = []

    class FakeSelector:
        def __init__(self, options: tuple[Any, ...], **_: Any) -> None:
            seen_options.extend((option.decision, option.label) for option in options)

        def choose(self) -> str:
            return "yes_all"

    monkeypatch.setattr("linuxagent.ui.console.ApprovalSelector", FakeSelector)
    ui = _english_console_ui()

    response = ui._approval_response(
        {
            "type": "confirm_command",
            "can_whitelist": True,
            "permission_candidates": [
                {"type": "Bash", "command": "cat /etc/os-release"},
                {"type": "Bash", "command": "nginx -v"},
            ],
        }
    )

    assert response == {
        "decision": "yes_all",
        "permissions": {
            "allow": ["Bash(cat /etc/os-release)", "Bash(nginx -v)"],
        },
    }
    assert seen_options == [
        ("yes", "Yes"),
        ("yes_all", "Yes, don't ask again in this conversation/resume"),
        ("no", "No"),
    ]


def test_command_approval_does_not_offer_allow_all_for_destructive_command(
    monkeypatch,
) -> None:
    seen_decisions: list[str] = []

    class FakeSelector:
        def __init__(self, options: tuple[Any, ...], **_: Any) -> None:
            seen_decisions.extend(option.decision for option in options)

        def choose(self) -> str:
            return "yes"

    monkeypatch.setattr("linuxagent.ui.console.ApprovalSelector", FakeSelector)
    ui = _english_console_ui()

    response = ui._approval_response(
        {
            "type": "confirm_command",
            "is_destructive": True,
            "can_whitelist": False,
            "permission_candidates": [{"type": "Bash", "command": "rm -rf /tmp/x"}],
        }
    )

    assert response == {"decision": "yes"}
    assert seen_decisions == ["yes", "no"]


def test_command_approval_does_not_offer_allow_all_when_policy_forbids_whitelist(
    monkeypatch,
) -> None:
    seen_decisions: list[str] = []

    class FakeSelector:
        def __init__(self, options: tuple[Any, ...], **_: Any) -> None:
            seen_decisions.extend(option.decision for option in options)

        def choose(self) -> str:
            return "yes"

    monkeypatch.setattr("linuxagent.ui.console.ApprovalSelector", FakeSelector)
    ui = _english_console_ui()

    response = ui._approval_response(
        {
            "type": "confirm_command",
            "is_destructive": False,
            "can_whitelist": False,
            "permission_candidates": [{"type": "Bash", "command": "python3 -c 'print(1)'"}],
        }
    )

    assert response == {"decision": "yes"}
    assert seen_decisions == ["yes", "no"]


def test_file_patch_approval_applies_all_when_all_files_confirmed(monkeypatch) -> None:
    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", lambda message, *, default: True)
    ui = _english_console_ui()

    response = ui._approval_response(
        {"type": "confirm_file_patch", "files_changed": ["one.py", "two.py"]}
    )

    assert response == {"decision": "yes"}


def test_file_patch_approval_refuses_when_no_files_confirmed(monkeypatch) -> None:
    monkeypatch.setattr("linuxagent.ui.console.Confirm.ask", lambda message, *, default: False)
    ui = _english_console_ui()

    response = ui._approval_response(
        {"type": "confirm_file_patch", "files_changed": ["one.py", "two.py"]}
    )

    assert response == {"decision": "no"}


def test_render_confirm_shows_batch_hosts() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

    ui._render_confirm(
        {
            "command": "uptime",
            "batch_hosts": ["web-1", "db-1"],
            "remote_profiles": [
                {
                    "host": "web-1",
                    "profile": "ops-ro",
                    "username": "ops",
                    "remote_cwd": "/srv/app",
                    "environment": "clean",
                    "allow_sudo": False,
                }
            ],
        }
    )

    rendered = console.export_text()
    assert "Batch hosts" in rendered
    assert "web-1, db-1" in rendered
    assert "Remote profiles" in rendered
    assert "profile=ops-ro" in rendered


def test_render_confirm_shows_destructive_warning() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

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


async def test_console_activity_from_worker_loop_runs_on_owner_loop() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)
    await ui.print_activity("owner-ready")

    done = threading.Event()
    worker_error: list[BaseException] = []

    def run_worker() -> None:
        try:
            asyncio.run(ui.print_activity("from-worker"))
        except BaseException as exc:
            worker_error.append(exc)
        finally:
            done.set()

    threading.Thread(target=run_worker, daemon=True).start()
    assert await _wait_for_event(done, deadline_seconds=1.0)
    if worker_error:
        raise worker_error[0]

    rendered = console.export_text()
    assert "owner-ready" in rendered
    assert "from-worker" in rendered


async def _wait_for_event(event: threading.Event, *, deadline_seconds: float) -> bool:
    deadline = asyncio.get_running_loop().time() + deadline_seconds
    while asyncio.get_running_loop().time() < deadline:
        if event.is_set():
            return True
        await asyncio.sleep(0.005)
    return event.is_set()


async def test_console_print_markdown_renders_model_output() -> None:
    console = Console(record=True, width=120)
    ui = ConsoleUI(console=console)

    await ui.print_markdown("### 能力\n\n- **执行命令**：查看系统")

    rendered = console.export_text()
    assert "能力" in rendered
    assert "执行命令：查看系统" in rendered
    assert "**执行命令**" not in rendered


async def test_console_print_activity_uses_transient_working_status(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity("LinuxAgent 正在规划命令")

    assert ui._working_status is not None
    assert ("bold ansibrightcyan", "linuxagent") in ui._build_prompt()
    assert ("ansibrightblack", "❯") in ui._build_prompt()
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中（0s • esc 中断）" in rendered
    assert "规划命令" in rendered
    assert "esc 中断" in rendered
    assert "╭" not in rendered
    assert "│" not in rendered
    assert "╰" not in rendered

    await ui.print("done")

    assert ui._working_status is None
    assert ui._build_prompt()
    final_rendered = console.export_text()
    assert "已完成步骤" not in final_rendered
    assert "规划命令" in final_rendered


async def test_console_print_activity_keeps_current_working_status(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity("LinuxAgent 正在分类意图")
    await ui.print_activity("LinuxAgent 正在规划命令")

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中（0s • esc 中断）" in rendered
    assert "规划命令" in rendered
    assert "分类意图" not in rendered
    assert "esc 中断" in rendered

    await ui.print("done")

    final_rendered = console.export_text()
    assert "已完成步骤" not in final_rendered


async def test_console_working_status_ignores_empty_working_step(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity("LinuxAgent 正在")
    await ui.print_activity("LinuxAgent 正在分类意图")

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中\n" not in rendered
    assert "分类意图" in rendered
    ui.clear_activity()


async def test_console_print_activity_supports_multiline_working_status(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity(
        "LinuxAgent 正在整理文件 workspace/disk_info.sh\n  read_file · 95 lines"
    )

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中（0s • esc 中断）" in rendered
    assert "esc 中断" in rendered
    assert "整理文件 workspace/disk_info.sh" in rendered
    assert "read_file · 95 lines" in rendered
    assert rendered.endswith("\n")

    await ui.print("done")

    assert ui._working_status is None


async def test_console_working_status_shows_pending_input_preview(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity("LinuxAgent 正在分类意图")
    await ui.update_pending_inputs(("后续问题",))

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "下次工具调用后将提交的消息" in rendered
    assert "后续问题" in rendered
    assert rendered.endswith("\n")

    await ui.print_user_input("后续问题")
    assert ui._pending_inputs == ()


async def test_console_print_activity_shows_parallel_agent_group(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity(
        "LinuxAgent 正在并发处理 只读批次：2/2\n"
        "  - agent A: running - 查 systemctl 状态\n"
        "  - agent B: done - 读取日志摘要"
    )

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中（0s • esc 中断）" in rendered
    assert "esc 中断" in rendered
    assert "并发处理 只读批次：2/2" in rendered
    assert "agent A: running - 查 systemctl 状态" in rendered
    assert "agent B: done - 读取日志摘要" in rendered

    await ui.print("done")

    assert ui._working_status is None


async def test_console_print_activity_preserves_elapsed_after_tool_status_clear(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    now = 100.0
    monkeypatch.setattr(console_module.time, "monotonic", lambda: now)
    monkeypatch.setattr(working_status_module.time, "monotonic", lambda: now)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity("LinuxAgent 正在列目录 /LinuxAgent")
    now = 103.0
    await ui.print_activity("LinuxAgent 无法读取文件 /etc/ansible/hosts\n  denied")
    await ui.print_activity("LinuxAgent 正在整理目录 /LinuxAgent\n  list_dir · 36 items")

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中（3s • esc 中断）" in rendered
    assert "整理目录 /LinuxAgent" in rendered
    ui.clear_activity()


async def test_console_print_activity_keeps_tool_failure_in_working_status(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    now = 100.0
    monkeypatch.setattr(console_module.time, "monotonic", lambda: now)
    monkeypatch.setattr(working_status_module.time, "monotonic", lambda: now)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_activity("LinuxAgent 正在读取文件 /etc/ansible/hosts")
    now = 102.0
    await ui.print_activity("LinuxAgent 无法读取文件 /etc/ansible/hosts\n  denied")

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中（2s • esc 中断）" in rendered
    assert "无法读取文件 /etc/ansible/hosts" in rendered
    assert "denied" in rendered
    ui.clear_activity()


async def test_console_print_active_view_renders_work_items(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="running",
            items=(
                ActiveWorkItemView(
                    item_id="intent",
                    category="graph",
                    status="completed",
                    label="分类意图",
                    summary="已完成",
                ),
                ActiveWorkItemView(
                    item_id="read",
                    category="tool",
                    status="running",
                    label="读取文件",
                    summary="/LinuxAgent/.work/plan/PlanC.md",
                ),
            ),
        )
    )

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中（0s • esc 中断）" in rendered
    assert "分类意图" in rendered
    assert "读取文件" in rendered
    assert "/LinuxAgent/.work/plan/PlanC.md" in rendered
    ui.clear_activity()


async def test_console_print_active_view_renders_i18n_label_params(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="running",
            items=(
                ActiveWorkItemView(
                    item_id="worker:trace:2",
                    category="worker",
                    status="running",
                    label="runtime.agent.command_worker",
                    label_params={"index": 2},
                    summary="runtime.agent.status.exit",
                    summary_params={"exit_code": 0},
                ),
            ),
        )
    )

    assert ui._working_status is not None
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "命令 worker 2" in rendered
    assert "exit 0" in rendered
    ui.clear_activity()


async def test_console_print_active_view_renders_plan_and_token_usage(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="running",
            token_usage=ActiveTokenUsageView(
                input_tokens=12000,
                output_tokens=1700,
                total_tokens=13700,
            ),
            items=(
                ActiveWorkItemView(
                    item_id="plan:trace",
                    category="plan",
                    status="running",
                    label="runtime.group.task_plan",
                    summary="复杂任务",
                    plan=(
                        ActivePlanItemView("收集上下文", "completed"),
                        ActivePlanItemView("生成答案", "in_progress"),
                    ),
                ),
            ),
        )
    )

    rendered = _render_working_status(ui, width=120)
    assert Translator(LanguageCode.ZH_CN).t("runtime.group.task_plan") in rendered
    assert "LinuxAgent · 处理中" in rendered
    assert "─" * 12 in rendered
    assert "复杂任务" in rendered
    assert "✓ 收集上下文" in rendered
    assert "□ 生成答案" in rendered
    assert "↓ 13.7k tokens" in rendered
    ui.clear_activity()


async def test_console_print_active_view_default_has_no_context_sidebar(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=132, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread-1234567890",
            turn_id="turn-abcdef",
            status="running",
            token_usage=ActiveTokenUsageView(total_tokens=13700),
            items=(
                ActiveWorkItemView(
                    item_id="intent",
                    category="graph",
                    status="completed",
                    label="分类意图",
                ),
                ActiveWorkItemView(
                    item_id="read",
                    category="tool",
                    status="running",
                    label="读取文件",
                    summary="/LinuxAgent/README.md",
                ),
            ),
        )
    )

    rendered = _render_working_status(ui, width=132)
    assert "Context" not in rendered
    assert "status  running" not in rendered
    assert "thread  thread-1..." not in rendered
    assert "tokens  ↓ 13.7k tokens" not in rendered
    assert "分类意图" in rendered
    assert "读取文件" in rendered
    assert "↓ 13.7k tokens" in rendered
    ui.clear_activity()


async def test_console_print_active_view_falls_back_on_narrow_terminal(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=80, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread-1234567890",
            turn_id="turn-abcdef",
            status="running",
            items=(
                ActiveWorkItemView(
                    item_id="read",
                    category="tool",
                    status="running",
                    label="读取文件",
                    summary="/LinuxAgent/README.md",
                ),
            ),
        )
    )

    rendered = _render_working_status(ui, width=80)
    assert "读取文件" in rendered
    assert "Context" not in rendered
    assert all(len(line) <= 80 for line in rendered.splitlines())
    ui.clear_activity()


async def test_console_print_active_view_compact_layout_matches_default(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=132, force_terminal=True)
    ui = ConsoleUI(console=console, tui_layout="compact")

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread-1234567890",
            turn_id="turn-abcdef",
            status="running",
            items=(
                ActiveWorkItemView(
                    item_id="read",
                    category="tool",
                    status="running",
                    label="读取文件",
                ),
            ),
        )
    )

    rendered = _render_working_status(ui, width=132)
    assert "读取文件" in rendered
    assert "Context" not in rendered
    ui.clear_activity()


def test_working_status_plan_item_marker_colors_completed_green() -> None:
    assert _plan_item_marker(ActivePlanItemView("done", "completed")) == ("✓", "green")
    assert _plan_item_marker(ActivePlanItemView("failed", "failed")) == ("✗", "red")


async def test_console_token_only_active_view_updates_prompt_without_status_block(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="completed",
            token_usage=ActiveTokenUsageView(
                input_tokens=12000,
                output_tokens=1700,
                total_tokens=13700,
            ),
        )
    )

    assert ui._working_status is None
    assert any("↓ 13.7k tokens" in fragment for _style, fragment in ui._build_prompt())


async def test_console_print_active_view_clears_on_terminal_status(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = ConsoleUI(console=console)

    await ui.print_active_view(
        ActiveTurnView(
            thread_id="thread",
            turn_id="turn",
            status="running",
            items=(
                ActiveWorkItemView(
                    item_id="intent",
                    category="graph",
                    status="running",
                    label="分类意图",
                ),
            ),
        )
    )
    assert ui._working_status is not None

    await ui.print_active_view(
        ActiveTurnView(thread_id="thread", turn_id="turn", status="completed")
    )

    assert ui._working_status is None


def test_working_status_cancel_skips_live_stop(monkeypatch) -> None:
    console = Console(record=True, width=120, force_terminal=True)
    status = WorkingStatus(console)
    status.update("LinuxAgent 正在分析意图")
    live = status._live
    assert live is not None

    stop_called = False

    def fake_stop() -> None:
        nonlocal stop_called
        stop_called = True

    monkeypatch.setattr(live, "stop", fake_stop)

    status.cancel()

    assert stop_called is False
    assert status._live is None
    assert not live.is_started


def test_working_status_limits_multiline_details() -> None:
    console = Console(record=True, width=120, force_terminal=True)
    status = WorkingStatus(console)

    status.update(
        "LinuxAgent 正在并发处理 只读批次：4/4\n"
        "  - agent A: running\n"
        "  - agent B: running\n"
        "  - agent C: running\n"
        "  - agent D: queued"
    )

    render_console = Console(record=True, width=120)
    render_console.print(status._render())
    rendered = render_console.export_text()

    assert "agent A: running" in rendered
    assert "agent B: running" in rendered
    assert "agent C: running..." in rendered
    assert "agent D: queued" not in rendered
    status.cancel()


def test_working_status_follows_current_stdout(monkeypatch) -> None:
    console = Console(record=True, width=120, force_terminal=True)
    original_file = console._file
    redirected = io.StringIO()
    monkeypatch.setattr(sys, "stdout", redirected)
    status = WorkingStatus(console)

    status.update("Working")
    status.stop()

    assert console._file is original_file
    assert redirected.getvalue()


def test_working_status_does_not_render_prompt_line() -> None:
    console = Console(record=True, width=120, force_terminal=True)
    status = WorkingStatus(console, translator=EN_TRANSLATOR)

    status.update("Classifying intent")

    assert status._live is not None
    render_console = Console(record=True, width=120)
    render_console.print(status._render())
    rendered = render_console.export_text()
    assert "linuxagent" not in rendered
    status.cancel()


def test_working_status_refreshes_multiline_view_timer(monkeypatch) -> None:
    console = Console(record=True, width=120, force_terminal=True)
    status = WorkingStatus(console)
    status.update("LinuxAgent 正在整理目录 /root/.linuxagent\n  list_dir · 17 items")
    live = status._live
    assert live is not None

    refreshes = 0

    def fake_refresh() -> None:
        nonlocal refreshes
        refreshes += 1

    monkeypatch.setattr(live, "refresh", fake_refresh)

    status.refresh()

    assert refreshes == 1
    status.cancel()


def test_working_status_keeps_periodic_refresh_for_single_line(monkeypatch) -> None:
    console = Console(record=True, width=120, force_terminal=True)
    status = WorkingStatus(console)
    status.update("LinuxAgent 正在分类意图")
    live = status._live
    assert live is not None

    refreshes = 0

    def fake_refresh() -> None:
        nonlocal refreshes
        refreshes += 1

    monkeypatch.setattr(live, "refresh", fake_refresh)

    status.refresh()

    assert refreshes == 1
    status.cancel()


async def test_console_print_activity_keeps_non_working_messages_plain(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = _english_console_ui(console)

    await ui.print_activity("LinuxAgent 命令结束：exit 0")

    assert ui._working_status is None
    assert "LinuxAgent 命令结束：exit 0" in console.export_text()


async def test_console_print_execution_result_can_show_compact_summary() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

    await ui.print_execution_result(
        ExecutionResult("/bin/echo marker", 0, "stdout-body\n", "", 0.1),
        include_output=False,
    )

    rendered = console.export_text()
    assert "Command result · exit 0" in rendered
    assert "/bin/echo marker" in rendered
    assert "stdout: 12 chars, 1 lines" in rendered
    assert "stdout-body" in rendered
    assert "[streamed above]" not in rendered
