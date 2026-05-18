"""Console UI tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from prompt_toolkit.document import Document
from rich.console import Console

from linuxagent.config.models import LanguageCode
from linuxagent.i18n import Translator
from linuxagent.interfaces import ExecutionResult
from linuxagent.ui import ConsoleUI
from linuxagent.ui.console import SlashCommandCompleter

EN_TRANSLATOR = Translator(LanguageCode.EN_US)


def _english_console_ui(console: Console | None = None) -> ConsoleUI:
    return ConsoleUI(console=console, translator=EN_TRANSLATOR)


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


def test_console_ui_prints_linuxagent_wordmark() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

    ui._print_hero()

    rendered = console.export_text()
    assert "████" in rendered
    assert "HITL-safe" not in rendered
    assert "▟▙" not in rendered
    assert "╭" not in rendered


def test_console_ui_uses_compact_wordmark_on_narrow_terminals() -> None:
    console = Console(record=True, width=40)
    ui = _english_console_ui(console)

    ui._print_hero()

    rendered = console.export_text()
    assert rendered.strip() == "LINUXAGENT"


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


def test_render_confirm_shows_only_remaining_runbook_steps() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

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
    render_console = Console(record=True, width=120)
    render_console.print(ui._working_status._render())
    rendered = render_console.export_text()
    assert "处理中: 规划命令" in rendered
    assert "esc 中断" in rendered
    assert "╭" not in rendered
    assert "│" not in rendered
    assert "╰" not in rendered
    assert "\n" not in rendered.rstrip("\n")

    await ui.print("done")

    assert ui._working_status is None


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
    assert "处理中（" in rendered
    assert "esc 中断" in rendered
    assert "整理文件 workspace/disk_info.sh" in rendered
    assert "read_file · 95 lines" in rendered

    await ui.print("done")

    assert ui._working_status is None


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
    assert "处理中（" in rendered
    assert "esc 中断" in rendered
    assert "并发处理 只读批次：2/2" in rendered
    assert "agent A: running - 查 systemctl 状态" in rendered
    assert "agent B: done - 读取日志摘要" in rendered

    await ui.print("done")

    assert ui._working_status is None


async def test_console_print_activity_keeps_non_working_messages_plain(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    console = Console(record=True, width=120, force_terminal=True)
    ui = _english_console_ui(console)

    await ui.print_activity("LinuxAgent 命令结束：exit 0")

    assert ui._working_status is None
    assert "LinuxAgent 命令结束：exit 0" in console.export_text()


async def test_console_print_execution_result_can_omit_streamed_output() -> None:
    console = Console(record=True, width=120)
    ui = _english_console_ui(console)

    await ui.print_execution_result(
        ExecutionResult("/bin/echo marker", 0, "stdout-body\n", "", 0.1),
        include_output=False,
    )

    rendered = console.export_text()
    assert "Command result · exit 0" in rendered
    assert "/bin/echo marker" in rendered
    assert "stdout-body" not in rendered
    assert "[streamed above]" in rendered
