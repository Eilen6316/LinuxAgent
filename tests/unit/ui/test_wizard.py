"""Wizard prompt-toolkit UI adapter tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prompt_toolkit.keys import Keys

from linuxagent.ui.wizard import WizardCheckpoint, render_fragments, wizard_key_bindings
from linuxagent.wizard.controller import WizardController
from linuxagent.wizard.models import WizardOption, WizardPlan, WizardStableState, WizardStep
from linuxagent.wizard.render_model import build_render_model


class _Event:
    def __init__(self, data: str = "") -> None:
        self.data = data


def _option(option_id: str) -> WizardOption:
    return WizardOption(id=option_id, label=option_id.title(), description="说明")


def _plan(kind: str = "single") -> WizardPlan:
    return WizardPlan(
        user_intent="部署服务",
        steps=(
            WizardStep(
                id="database",
                title="数据库",
                kind=kind,  # type: ignore[arg-type]
                options=(_option("postgres"), _option("mysql"), _option("sqlite")),
            ),
        ),
    )


def _two_step_plan() -> WizardPlan:
    return WizardPlan(
        user_intent="部署服务",
        steps=(
            WizardStep(
                id="database",
                title="数据库",
                kind="single",
                options=(_option("postgres"), _option("mysql"), _option("sqlite")),
            ),
            WizardStep(
                id="target",
                title="环境",
                kind="single",
                options=(_option("dev"), _option("stage"), _option("prod")),
            ),
        ),
    )


def _long_plan() -> WizardPlan:
    long_text = "abcdefghij" * 20
    return WizardPlan(
        user_intent=long_text,
        steps=(
            WizardStep(
                id="database",
                title=long_text,
                kind="single",
                options=(
                    WizardOption(id="postgres", label=long_text, description="说明"),
                    _option("mysql"),
                    _option("sqlite"),
                ),
            ),
        ),
    )


def _handlers(bindings: Any) -> dict[str, Callable[[object], None]]:
    output: dict[str, Callable[[object], None]] = {}
    for binding in bindings.bindings:
        key = binding.keys[0]
        name = key.value if isinstance(key, Keys) else str(key)
        output[name] = binding.handler
        if name == "c-m":
            output["enter"] = binding.handler
        if name == "c-h":
            output["backspace"] = binding.handler
    return output


def test_render_fragments_include_required_sections() -> None:
    controller = WizardController(_plan())
    rendered = "".join(
        str(fragment[1]) for fragment in render_fragments(build_render_model(controller))
    )

    assert "部署服务" in rendered
    assert "数据库" in rendered
    assert "Type something" in rendered
    assert "Chat about this" in rendered
    assert "Enter to select" in rendered


def test_single_render_does_not_show_checkbox() -> None:
    controller = WizardController(_plan("single"))
    rendered = "".join(
        str(fragment[1]) for fragment in render_fragments(build_render_model(controller))
    )

    assert "[ ]" not in rendered


def test_multi_render_shows_checkbox() -> None:
    controller = WizardController(_plan("multi"))
    rendered = "".join(
        str(fragment[1]) for fragment in render_fragments(build_render_model(controller))
    )

    assert "[ ]" in rendered


def test_render_fragments_truncate_long_fields_without_mutating_controller_state() -> None:
    controller = WizardController(_long_plan())
    controller.focus_option_number(4)
    controller.start_text_edit()
    controller.append_text("x" * 160)

    rendered = "".join(
        str(fragment[1]) for fragment in render_fragments(build_render_model(controller))
    )

    assert "..." in rendered
    assert "x" * 160 not in rendered
    assert controller.text_buffer == "x" * 160


def test_key_bindings_drive_controller() -> None:
    controller = WizardController(_plan())
    exits: list[str] = []
    bindings = wizard_key_bindings(controller, lambda result: exits.append(result.status))
    handlers = _handlers(bindings)

    handlers["down"](_Event())
    assert controller.option_focus_index == 1
    handlers["1"](_Event())
    assert controller.option_focus_index == 0
    handlers["enter"](_Event())

    assert exits == []
    assert controller.is_submit_tab
    handlers["enter"](_Event())
    assert exits == ["submit"]


def test_key_bindings_keep_single_tui_until_submit() -> None:
    controller = WizardController(_two_step_plan())
    exits: list[str] = []
    bindings = wizard_key_bindings(controller, lambda result: exits.append(result.status))
    handlers = _handlers(bindings)

    handlers["enter"](_Event())

    assert exits == []
    assert controller.current_step_id == "target"
    controller.previous_step()
    assert controller.current_step_id == "database"
    controller.next_step()
    handlers["enter"](_Event())

    assert exits == []
    assert controller.is_submit_tab
    handlers["enter"](_Event())
    assert exits == ["submit"]


def test_key_bindings_checkpoint_only_stable_answer_changes() -> None:
    controller = WizardController(_plan())
    stable_states: list[WizardStableState] = []
    bindings = wizard_key_bindings(
        controller,
        lambda result: None,
        on_stable_state=stable_states.append,
    )
    handlers = _handlers(bindings)

    handlers["down"](_Event())
    handlers["<any>"](_Event("x"))
    assert stable_states == []

    handlers["enter"](_Event())

    assert len(stable_states) == 1
    assert stable_states[0].answers[0].step_id == "database"


def test_key_bindings_can_exit_with_checkpoint_on_stable_answer_change() -> None:
    controller = WizardController(_plan())
    exits: list[object] = []
    bindings = wizard_key_bindings(
        controller,
        exits.append,
        checkpoint_on_stable_state=True,
    )
    handlers = _handlers(bindings)

    handlers["enter"](_Event())

    assert isinstance(exits[0], WizardCheckpoint)
    assert exits[0].stable_state.answers[0].step_id == "database"


def test_key_bindings_checkpoint_text_commit_only() -> None:
    controller = WizardController(_plan())
    stable_states: list[WizardStableState] = []
    bindings = wizard_key_bindings(
        controller,
        lambda result: None,
        on_stable_state=stable_states.append,
    )
    handlers = _handlers(bindings)

    controller.focus_option_number(4)
    handlers["e"](_Event())
    handlers["<any>"](_Event("a"))
    handlers["<any>"](_Event("b"))
    assert stable_states == []

    handlers["enter"](_Event())

    assert len(stable_states) == 1
    assert stable_states[0].answers[0].text == "ab"


def test_text_edit_bindings() -> None:
    controller = WizardController(_plan())
    bindings = wizard_key_bindings(controller, lambda result: None)
    handlers = _handlers(bindings)

    controller.focus_option_number(4)
    handlers["e"](_Event())
    handlers["<any>"](_Event("a"))
    handlers["<any>"](_Event("b"))
    handlers["backspace"](_Event())
    assert controller.text_buffer == "a"
    handlers["c-u"](_Event())
    assert controller.text_buffer == ""
    handlers["escape"](_Event())
    assert controller.editing_text is False
