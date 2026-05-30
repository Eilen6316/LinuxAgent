"""Modern Rich-powered terminal UI for LinuxAgent."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncGenerator, Callable, Coroutine
from concurrent.futures import Future as ConcurrentFuture
from pathlib import Path
from typing import Any

from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from .. import __version__
from ..active_view import ActiveTurnView
from ..execution_display import execution_display_text, execution_summary_text
from ..i18n import Translator, default_translator
from ..interfaces import ExecutionResult, UserInterface
from .approval_selector import ApprovalOption, ApprovalSelector
from .confirmation_renderer import ConfirmationRenderer
from .diff_renderer import (
    DiffRenderer,
    diff_file_title,
    diff_line_style,
    parse_unified_diff_files,
    render_unified_diff,
)
from .prompt_session import PromptSessionManager, SlashCommandCompleter
from .resume_selector import ResumeSelector
from .working_status import WORKING_REFRESH_PER_SECOND, WorkingStatus, _working_label

__all__ = ["ConsoleUI", "SlashCommandCompleter"]


class ConsoleUI(UserInterface):
    def __init__(
        self,
        *,
        console: Console | None = None,
        theme: str = "auto",
        tui_layout: str = "wide",
        prompt_symbol: str = "❯",
        history_path: Path | None = None,
        session_factory: Any | None = None,
        translator: Translator | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self._console = console or Console()
        self._theme = theme
        self._tui_layout = tui_layout
        self._prompt_symbol = prompt_symbol
        self._history_path = history_path or (Path.home() / ".linuxagent" / "prompt_history")
        self._translator = translator or default_translator()
        self._provider = provider
        self._model = model
        self._activity_visible = True
        self._working_status: WorkingStatus | None = None
        self._activity_started_at: float | None = None
        self._activity_generation = 0
        self._pending_inputs: tuple[str, ...] = ()
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._cancel_reason = "escape"
        self._working_refresh_task: asyncio.Task[None] | None = None
        self._prompt_session = PromptSessionManager(
            theme=theme,
            prompt_symbol=prompt_symbol,
            history_path=self._history_path,
            session_factory=session_factory,
            translator=self._translator,
        )
        self._prompt_session.set_cancel_event(self._cancel_event, self._set_cancel_reason)
        self._confirmation_renderer = ConfirmationRenderer(
            self._console,
            theme=theme,
            translator=self._translator,
        )

    async def input_stream(self) -> AsyncGenerator[str, None]:
        self._bind_owner_loop()
        if not sys.stdin.isatty():
            return
        self._print_hero()
        session = self._prompt_session.create_session()
        while True:
            with patch_stdout(raw=True):
                try:
                    line = await session.prompt_async(self._prompt_session.dynamic_prompt(session))
                except (EOFError, KeyboardInterrupt):
                    return
            if line.strip():
                yield line

    async def handle_interrupt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._bind_owner_loop()
        started = time.monotonic()
        self.clear_activity()
        if not sys.stdin.isatty():
            return {"decision": "non_tty_auto_deny", "latency_ms": 0}
        self._confirmation_renderer.render(payload)
        response = self._approval_response(payload)
        response["latency_ms"] = int((time.monotonic() - started) * 1000)
        self._print_approval_summary(payload, response)
        return response

    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and self._console.is_terminal

    async def print(self, text: str) -> None:
        if await self._run_on_owner_loop(lambda: self.print(text)):
            return
        self.clear_activity()
        self._print_to_current_stdout(Panel(Text(text), border_style=self._panel_style()))

    async def print_markdown(self, text: str) -> None:
        if await self._run_on_owner_loop(lambda: self.print_markdown(text)):
            return
        self.clear_activity()
        self._print_to_current_stdout(Panel(Markdown(text), border_style=self._panel_style()))

    async def print_user_input(self, text: str) -> None:
        if await self._run_on_owner_loop(lambda: self.print_user_input(text)):
            return
        self._prompt_session.set_token_usage(None)
        self._remove_pending_input(text)
        self.clear_activity()
        self._print_to_current_stdout(
            Panel(
                Text(text),
                title=self._translator.t("resume.role.human"),
                border_style="bright_black",
            )
        )
        self._print_to_current_stdout()

    async def update_pending_inputs(self, inputs: tuple[str, ...]) -> None:
        if await self._run_on_owner_loop(lambda: self.update_pending_inputs(inputs)):
            return
        self._pending_inputs = inputs
        if self._working_status is not None:
            self._working_status.update_pending_inputs(inputs)

    async def print_raw(self, text: str, *, stderr: bool = False) -> None:
        if await self._run_on_owner_loop(lambda: self.print_raw(text, stderr=stderr)):
            return
        self._clear_activity(reset_timer=False)
        rendered = Text(text, style="red") if stderr else Text(text)
        self._print_to_current_stdout(rendered, end="")

    async def print_execution_result(
        self, result: ExecutionResult, *, include_output: bool = True
    ) -> None:
        if await self._run_on_owner_loop(
            lambda: self.print_execution_result(result, include_output=include_output)
        ):
            return
        self._clear_activity(reset_timer=False)
        display = _execution_result_display(result, include_output=include_output)
        style = "green" if result.exit_code == 0 else "red"
        title = self._translator.t("ui.console.command_result_title", exit_code=result.exit_code)
        self._print_to_current_stdout(Panel(Text(display.text), title=title, border_style=style))

    async def print_activity(self, text: str) -> None:
        if await self._run_on_owner_loop(lambda: self.print_activity(text)):
            return
        if not self._activity_visible:
            return
        if self._is_transient_activity(text) and sys.stdin.isatty() and self._console.is_terminal:
            self.start_working(text)
            return
        self._clear_activity(reset_timer=False)
        self._print_to_current_stdout(Text(text, style="dim"))

    async def print_active_view(self, view: ActiveTurnView) -> None:
        if await self._run_on_owner_loop(lambda: self.print_active_view(view)):
            return
        self._prompt_session.set_token_usage(view.token_usage)
        if _token_only_active_view(view):
            self._clear_activity(reset_timer=False)
            return
        if _terminal_active_view(view):
            self._clear_activity(reset_timer=False)
            return
        self._render_active_view(view)

    def start_working(self, text: str = "Working") -> None:
        self._bind_owner_loop()
        self._cancel_event.clear()
        self._cancel_reason = "escape"
        if not self._activity_visible:
            return
        if not sys.stdin.isatty() or not self._console.is_terminal:
            return
        self._prompt_session.set_activity_busy(True)
        now = time.monotonic()
        if self._starts_new_activity_cycle(text) or self._activity_started_at is None:
            self._activity_started_at = now
        if self._working_status is None:
            self._working_status = WorkingStatus(
                self._console,
                theme=self._theme,
                layout=self._tui_layout,
                translator=self._translator,
                started_at=self._activity_started_at,
            )
        else:
            self._working_status.set_started_at(self._activity_started_at)
        self._working_status.update(text)
        self._working_status.update_pending_inputs(self._pending_inputs)
        self._ensure_working_refresh_task()

    def _render_active_view(self, view: ActiveTurnView) -> None:
        if not self._activity_visible:
            return
        if not sys.stdin.isatty() or not self._console.is_terminal:
            return
        if self._activity_started_at is None:
            self._activity_started_at = time.monotonic()
        if self._working_status is None:
            self._working_status = WorkingStatus(
                self._console,
                theme=self._theme,
                layout=self._tui_layout,
                translator=self._translator,
                started_at=self._activity_started_at,
            )
        else:
            self._working_status.set_started_at(self._activity_started_at)
        self._working_status.update_view(view)
        self._working_status.update_pending_inputs(self._pending_inputs)
        self._ensure_working_refresh_task()

    def clear_activity(self) -> None:
        self._clear_activity(reset_timer=True)

    def _clear_activity(self, *, reset_timer: bool) -> None:
        self._activity_generation += 1
        self._stop_working_refresh_task()
        if self._working_status is not None:
            self._working_status.cancel()
            self._working_status = None
        if reset_timer:
            self._activity_started_at = None
            self._prompt_session.set_activity_busy(False)

    def _starts_new_activity_cycle(self, text: str) -> bool:
        return _working_label(text, self._translator) == self._translator.t("ui.working.title")

    def _is_transient_activity(self, text: str) -> bool:
        if text.startswith(self._translator.t("ui.working.activity_prefix")):
            return True
        return any(text.startswith(prefix) for prefix in self._tool_failure_activity_prefixes())

    def _tool_failure_activity_prefixes(self) -> tuple[str, ...]:
        specs: tuple[tuple[str, dict[str, str]], ...] = (
            ("runtime.tool.activity_guidance_failed", {"path": ""}),
            ("runtime.tool.activity_read_failed", {"path": ""}),
            ("runtime.tool.activity_list_failed", {"path": ""}),
            ("runtime.tool.activity_search_failed", {"target": ""}),
        )
        return tuple(
            prefix for key, params in specs if (prefix := self._translator.t(key, **params).strip())
        )

    def _ensure_working_refresh_task(self) -> None:
        if self._working_refresh_task is not None and not self._working_refresh_task.done():
            return
        if self._owner_loop is not None and self._owner_loop is not asyncio.get_running_loop():
            return
        self._working_refresh_task = asyncio.create_task(self._refresh_working_status())

    def _stop_working_refresh_task(self) -> None:
        task = self._working_refresh_task
        self._working_refresh_task = None
        if task is not None and not task.done():
            task.cancel()
            task.add_done_callback(_consume_async_task_result)

    async def _refresh_working_status(self) -> None:
        delay = 1 / WORKING_REFRESH_PER_SECOND
        while self._working_status is not None:
            await asyncio.sleep(delay)
            if self._working_status is not None:
                self._working_status.refresh()

    def _print_to_current_stdout(self, *objects: Any, **kwargs: Any) -> None:
        if self._console.file is sys.stdout:
            self._console.print(*objects, **kwargs)
            return
        original = self._console._file
        self._console.file = sys.stdout
        try:
            self._console.print(*objects, **kwargs)
        finally:
            self._console._file = original

    async def cancel_activity(self, reason: str) -> None:
        if await self._run_on_owner_loop(lambda: self.cancel_activity(reason)):
            return
        self._activity_generation += 1
        self._stop_working_refresh_task()
        if self._working_status is not None:
            self._working_status.cancel()
            self._working_status = None
        self._activity_started_at = None
        self._prompt_session.set_activity_busy(False)

    def _remove_pending_input(self, text: str) -> None:
        if not self._pending_inputs:
            return
        pending = list(self._pending_inputs)
        try:
            pending.remove(text)
        except ValueError:
            return
        self._pending_inputs = tuple(pending)

    def set_activity_visible(self, visible: bool) -> None:
        if not visible:
            self.clear_activity()
        self._activity_visible = visible

    def supports_resume_selector(self) -> bool:
        return sys.stdin.isatty()

    async def choose_resume_session(self, sessions: list[Any]) -> str | None:
        self._bind_owner_loop()
        self.clear_activity()
        if not sys.stdin.isatty():
            return None
        return await ResumeSelector(sessions, translator=self._translator).choose()

    async def wait_for_cancel(self) -> str:
        self._bind_owner_loop()
        if not sys.stdin.isatty():
            return await super().wait_for_cancel()
        await self._cancel_event.wait()
        return self._cancel_reason

    def request_pending_input_interrupt(self) -> bool:
        if not self._pending_inputs:
            return False
        self._set_cancel_reason("pending_input")
        self._cancel_event.set()
        return True

    def _set_cancel_reason(self, reason: str) -> None:
        self._cancel_reason = reason

    def _bind_owner_loop(self) -> None:
        if self._owner_loop is not None:
            return
        try:
            self._owner_loop = asyncio.get_running_loop()
        except RuntimeError:
            return

    async def _run_on_owner_loop(self, action: Callable[[], Coroutine[Any, Any, None]]) -> bool:
        loop = asyncio.get_running_loop()
        owner_loop = self._owner_loop
        if owner_loop is None:
            self._owner_loop = loop
            return False
        if owner_loop is loop:
            return False
        action_coro = action()
        try:
            future: ConcurrentFuture[None] = asyncio.run_coroutine_threadsafe(
                self._run_posted_ui_action(action_coro, self._activity_generation),
                owner_loop,
            )
        except RuntimeError:
            action_coro.close()
            return True
        future.add_done_callback(_consume_threadsafe_ui_result)
        return True

    async def _run_posted_ui_action(
        self,
        action_coro: Coroutine[Any, Any, None],
        generation: int,
    ) -> None:
        if generation != self._activity_generation:
            action_coro.close()
            return
        await action_coro

    def _print_hero(self) -> None:
        self.clear_activity()
        self._console.print(self._hero_text())
        if self._console.width < HERO_MIN_WIDTH:
            return
        tagline = self._translator.t("ui.hero.tagline")
        self._console.print(Text(f"  {tagline}", style="dim"))
        self._console.print(Text(f"  {self._hero_meta_line()}", style="dim"))
        divider_width = max(20, min(80, self._console.width - 2))
        self._console.print(Text(f"  {'─' * divider_width}", style="dim"))

    def _hero_text(self) -> Text:
        if self._console.width < HERO_MIN_WIDTH:
            return self._compact_hero_text()
        if self._theme == "light":
            hero = Text()
            for line in HERO_WORD:
                hero.append(f"{line}\n", style=f"bold {self._accent_style()}")
            return hero
        width = max(len(line) for line in HERO_WORD)
        hero = Text()
        for line in HERO_WORD:
            for col, ch in enumerate(line):
                if ch == " ":
                    hero.append(ch)
                else:
                    hero.append(ch, style=f"bold {_hero_gradient_color(col, width)}")
            hero.append("\n")
        return hero

    def _compact_hero_text(self) -> Text:
        hero = Text()
        hero.append("LINUXAGENT", style=f"bold {self._accent_style()}")
        hero.append(f"  v{__version__}", style="dim")
        return hero

    def _hero_meta_line(self) -> str:
        if self._provider and self._model:
            return self._translator.t(
                "ui.hero.meta_full",
                version=__version__,
                provider=self._provider,
                model=self._model,
            )
        return self._translator.t("ui.hero.meta_short", version=__version__)

    def _render_confirm(self, payload: dict[str, Any]) -> None:
        self.clear_activity()
        self._confirmation_renderer.render_command(payload)

    def _render_file_patch_confirm(self, payload: dict[str, Any]) -> None:
        self.clear_activity()
        self._confirmation_renderer.render_file_patch(payload)

    def _build_prompt(self, current_text: str = "") -> list[tuple[str, str]]:
        return self._prompt_session.build_prompt(current_text)

    def _default_session_factory(self) -> Any:
        return self._prompt_session._default_session_factory()

    def _accent_style(self) -> str:
        if self._theme == "light":
            return "blue"
        if self._theme == "dark":
            return "bright_cyan"
        return "bright_cyan"

    def _panel_style(self) -> str:
        if self._theme == "light":
            return "blue"
        return "bright_black"

    def _approval_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        files = tuple(str(item) for item in payload.get("files_changed", ()) if str(item))
        if payload.get("type") == "confirm_file_patch":
            _review_file_patch_diff(payload, self._console, self._translator)
        if payload.get("type") == "confirm_file_patch" and len(files) > 1:
            return _file_patch_approval_response(files, self._translator)
        if payload.get("type") == "confirm_command":
            return _command_approval_response(payload, self._translator)
        approved = Confirm.ask(
            f"[bold]{self._translator.t('ui.confirm.allow_operation')}[/]", default=False
        )
        return {"decision": "yes" if approved else "no"}

    def _print_approval_summary(self, payload: dict[str, Any], response: dict[str, Any]) -> None:
        summary = _approval_summary(payload, response, self._translator)
        if summary:
            self._console.print(Text(summary, style="dim"))


_render_unified_diff = render_unified_diff
_diff_line_style = diff_line_style

HERO_MIN_WIDTH = 86
HERO_WORD = (
    "  ██      ██ ███    ██ ██    ██ ██   ██  █████   ██████  ███████ ███    ██ ████████",
    "  ██      ██ ████   ██ ██    ██  ██ ██  ██   ██ ██       ██      ████   ██    ██",
    "  ██      ██ ██ ██  ██ ██    ██   ███   ███████ ██   ███ █████   ██ ██  ██    ██",
    "  ██      ██ ██  ██ ██ ██    ██  ██ ██  ██   ██ ██    ██ ██      ██  ██ ██    ██",
    "  ███████ ██ ██   ████  ██████  ██   ██ ██   ██  ██████  ███████ ██   ████    ██",
)
_HERO_GRADIENT_START = (0, 212, 255)
_HERO_GRADIENT_END = (255, 102, 217)


def _hero_gradient_color(col: int, width: int) -> str:
    t = col / max(1, width - 1)
    r = int(_HERO_GRADIENT_START[0] + (_HERO_GRADIENT_END[0] - _HERO_GRADIENT_START[0]) * t)
    g = int(_HERO_GRADIENT_START[1] + (_HERO_GRADIENT_END[1] - _HERO_GRADIENT_START[1]) * t)
    b = int(_HERO_GRADIENT_START[2] + (_HERO_GRADIENT_END[2] - _HERO_GRADIENT_START[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _file_patch_approval_response(
    files: tuple[str, ...], translator: Translator | None = None
) -> dict[str, Any]:
    translator = translator or default_translator()
    selected = tuple(
        file
        for file in files
        if Confirm.ask(
            f"[bold]{translator.t('ui.confirm.apply_file', file=file)}[/]",
            default=True,
        )
    )
    if not selected:
        return {"decision": "no"}
    if selected == files:
        return {"decision": "yes"}
    return {"decision": "yes", "selected_files": list(selected)}


def _command_approval_response(
    payload: dict[str, Any], translator: Translator | None = None
) -> dict[str, Any]:
    translator = translator or default_translator()
    decision = ApprovalSelector(
        _approval_options(payload, translator), translator=translator
    ).choose()
    if decision == "yes_all":
        return {
            "decision": "yes_all",
            "permissions": {
                "allow": [f"Bash({item['command']})" for item in _permission_candidates(payload)]
            },
        }
    return {"decision": "yes" if decision == "yes" else "no"}


def _approval_options(
    payload: dict[str, Any], translator: Translator | None = None
) -> tuple[ApprovalOption, ...]:
    translator = translator or default_translator()
    options = [
        ApprovalOption(
            "y",
            "yes",
            translator.t("ui.approval.yes_label"),
            translator.t("ui.approval.yes_description"),
        )
    ]
    if _can_allow_conversation(payload):
        options.append(
            ApprovalOption(
                "a",
                "yes_all",
                translator.t("ui.approval.yes_all_label"),
                translator.t("ui.approval.yes_all_description"),
            )
        )
    options.append(
        ApprovalOption(
            "n",
            "no",
            translator.t("ui.approval.no_label"),
            translator.t("ui.approval.no_description"),
        )
    )
    return tuple(options)


def _can_allow_conversation(payload: dict[str, Any]) -> bool:
    return (
        payload.get("type") == "confirm_command"
        and bool(payload.get("can_whitelist", True))
        and not payload.get("is_destructive", False)
        and not payload.get("batch_hosts")
        and bool(_permission_candidates(payload))
    )


def _permission_candidates(payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates = payload.get("permission_candidates") or []
    return [
        item
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("command"), str)
    ]


def _execution_result_display(result: ExecutionResult, *, include_output: bool) -> Any:
    if include_output:
        return execution_display_text(result)
    return execution_summary_text(result)


def _consume_threadsafe_ui_result(future: ConcurrentFuture[None]) -> None:
    try:
        future.result()
    except (RuntimeError, asyncio.CancelledError):
        return
    except Exception:  # noqa: BLE001 - UI refresh failures must not fail worker execution
        return


def _consume_async_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return


def _terminal_active_view(view: ActiveTurnView) -> bool:
    return view.status in {"completed", "failed", "cancelled"}


def _token_only_active_view(view: ActiveTurnView) -> bool:
    return view.token_usage is not None and not view.items and view.pending_request is None


def _approval_summary(
    payload: dict[str, Any], response: dict[str, Any], translator: Translator
) -> str:
    decision = str(response.get("decision") or "no")
    key = _approval_summary_key(decision)
    subject = _approval_subject(payload, translator)
    return translator.t(key, subject=subject)


def _approval_summary_key(decision: str) -> str:
    if decision == "yes":
        return "ui.approval.summary.yes"
    if decision == "yes_all":
        return "ui.approval.summary.yes_all"
    return "ui.approval.summary.no"


def _approval_subject(payload: dict[str, Any], translator: Translator) -> str:
    if payload.get("type") == "confirm_file_patch":
        files = [str(item) for item in payload.get("files_changed", ()) if str(item)]
        return translator.t("ui.approval.summary.file_patch", count=len(files))
    command = str(payload.get("command") or payload.get("type") or "")
    return _compact_subject(command)


def _compact_subject(value: str, *, limit: int = 120) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _review_file_patch_diff(
    payload: dict[str, Any], console: Console, translator: Translator | None = None
) -> None:
    translator = translator or default_translator()
    files = parse_unified_diff_files(str(payload.get("unified_diff") or ""))
    if not files:
        return
    renderer = DiffRenderer(translator=translator)
    for file in files:
        if renderer.page_count(file) <= 1:
            continue
        if not Confirm.ask(
            f"[bold]{translator.t('ui.confirm.show_hidden_diff_pages', file=file.display_path)}[/]",
            default=False,
        ):
            continue
        _page_file_diff(console, renderer, file, start_page=2, translator=translator)


def _page_file_diff(
    console: Console,
    renderer: DiffRenderer,
    file: Any,
    *,
    start_page: int = 1,
    translator: Translator | None = None,
) -> None:
    translator = translator or default_translator()
    page_count = renderer.page_count(file)
    page = max(1, min(start_page, page_count))
    while page <= page_count:
        console.print(
            Panel(
                renderer.render_file_page(file, page),
                title=f"[bold]{diff_file_title(file, translator)}[/]",
                border_style="bright_magenta",
                padding=(1, 2),
            )
        )
        if page >= page_count:
            return
        if not Confirm.ask(
            (
                f"[bold]{translator.t('ui.confirm.show_next_hidden_diff_page', file=file.display_path, page=page + 1, page_count=page_count)}[/]"
            ),
            default=True,
        ):
            return
        page += 1


def _resume_choice_label(session: Any) -> str:
    label = getattr(session, "label", None)
    if isinstance(label, str):
        return label
    title = str(getattr(session, "title", "Untitled session"))
    messages = tuple(getattr(session, "messages", ()))
    compact_title = title if len(title) <= 72 else f"{title[:69]}..."
    return f"{compact_title}  [{len(messages)} messages]"
