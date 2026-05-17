# mypy: disable-error-code=misc
"""Prompt-toolkit UI adapter for the wizard controller."""

from __future__ import annotations

from collections.abc import Callable

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from ..wizard import WizardController, WizardPlan, WizardResult
from ..wizard.render_model import WizardOptionRow, WizardRenderModel, build_render_model

_USER_INTENT_LIMIT = 120
_ROW_LABEL_LIMIT = 48
_DESCRIPTION_LIMIT = 72


class WizardTUI:
    def __init__(self, plan: WizardPlan) -> None:
        self.controller = WizardController(plan)
        self._control = FormattedTextControl(self._fragments, focusable=True)
        self._application: Application[WizardResult] = Application(
            layout=Layout(HSplit([Window(self._control, wrap_lines=False)])),
            key_bindings=wizard_key_bindings(self.controller, self._exit),
            style=_style(),
            full_screen=True,
        )

    async def run_async(self) -> WizardResult:
        result = await self._application.run_async()
        if isinstance(result, WizardResult):
            return result
        raise RuntimeError("wizard TUI exited without a WizardResult")

    def _exit(self, result: WizardResult) -> None:
        get_app().exit(result=result)

    def _fragments(self) -> StyleAndTextTuples:
        return render_fragments(build_render_model(self.controller))


def render_fragments(model: WizardRenderModel) -> StyleAndTextTuples:
    fragments: StyleAndTextTuples = []
    fragments.extend([("class:dim", _truncate(model.user_intent, _USER_INTENT_LIMIT)), ("", "\n")])
    fragments.extend(_tab_fragments(model))
    fragments.extend([("", "\n\n"), ("class:title", model.current_title), ("", "\n")])
    for index, row in enumerate(model.option_rows, start=1):
        fragments.extend(_row_fragments(index, row))
    if model.editing_text:
        fragments.extend([("class:input", f"\n> {model.text_buffer}")])
    fragments.extend([("", "\n"), ("class:dim", model.footer_text)])
    return fragments


def wizard_key_bindings(
    controller: WizardController,
    exit_callback: Callable[[WizardResult], None],
) -> KeyBindings:
    bindings = KeyBindings()
    _bind_navigation(bindings, controller)
    _bind_selection(bindings, controller, exit_callback)
    _bind_text_editing(bindings, controller, exit_callback)
    return bindings


def _bind_navigation(bindings: KeyBindings, controller: WizardController) -> None:
    @bindings.add("right")
    @bindings.add("tab")
    def _next_tab(_event: object) -> None:
        controller.next_step()

    @bindings.add("left")
    @bindings.add("s-tab")
    def _previous_tab(_event: object) -> None:
        controller.previous_step()

    @bindings.add("up")
    def _up(_event: object) -> None:
        controller.move_option(-1)

    @bindings.add("down")
    def _down(_event: object) -> None:
        controller.move_option(1)

    for number in range(1, 7):
        _bind_number(bindings, controller, number)


def _bind_selection(
    bindings: KeyBindings,
    controller: WizardController,
    exit_callback: Callable[[WizardResult], None],
) -> None:
    @bindings.add("enter")
    def _enter(_event: object) -> None:
        result = controller.enter()
        if result is not None:
            exit_callback(result)

    @bindings.add("e")
    def _edit(_event: object) -> None:
        if controller.focused_row_kind == "type_something":
            controller.start_text_edit()


def _bind_text_editing(
    bindings: KeyBindings,
    controller: WizardController,
    exit_callback: Callable[[WizardResult], None],
) -> None:
    @bindings.add("backspace")
    def _backspace(_event: object) -> None:
        controller.backspace_text()

    @bindings.add("c-u")
    def _clear(_event: object) -> None:
        controller.clear_text()

    @bindings.add("escape")
    def _escape(_event: object) -> None:
        result = controller.escape()
        if result is not None:
            exit_callback(result)

    @bindings.add("<any>")
    def _append(event: object) -> None:
        data = getattr(event, "data", "")
        if data:
            controller.append_text(str(data))


async def run_wizard(plan: WizardPlan) -> WizardResult:
    """Run the full-screen wizard TUI."""
    return await WizardTUI(plan).run_async()


def _bind_number(bindings: KeyBindings, controller: WizardController, number: int) -> None:
    @bindings.add(str(number))
    def _number(_event: object, value: int = number) -> None:
        controller.focus_option_number(value)


def _tab_fragments(model: WizardRenderModel) -> StyleAndTextTuples:
    fragments: StyleAndTextTuples = [("class:dim", "← ")]
    for tab in model.tabs:
        style = "class:tab.current" if tab.current else "class:tab"
        if not tab.enabled:
            style = "class:dim"
        fragments.extend([(style, tab.display), ("", "  ")])
    fragments.append(("class:dim", "→"))
    return fragments


def _row_fragments(index: int, row: WizardOptionRow) -> StyleAndTextTuples:
    pointer = "› " if row.focused else "  "
    label = _truncate(row.label, _ROW_LABEL_LIMIT)
    description = _truncate(row.description, _DESCRIPTION_LIMIT)
    if row.kind == "option" and row.multi:
        marker = "[x]" if row.selected else "[ ]"
    elif row.kind == "option" and row.selected:
        marker = "✓"
    else:
        marker = " "
    style = "class:row.focused" if row.focused else "class:row"
    return [
        (style, f"{pointer}{index}. {marker} {label}\n"),
        ("class:dim", f"     {description}\n"),
    ]


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _style() -> Style:
    return Style.from_dict(
        {
            "dim": "ansibrightblack",
            "title": "bold",
            "tab.current": "bold ansicyan",
            "tab": "",
            "row.focused": "reverse",
            "row": "",
            "input": "ansigreen",
        }
    )
