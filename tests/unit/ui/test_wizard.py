"""Wizard prompt-toolkit UI adapter tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prompt_toolkit.keys import Keys

from linuxagent.ui.wizard import render_fragments, wizard_key_bindings
from linuxagent.wizard.controller import WizardController
from linuxagent.wizard.models import WizardOption, WizardPlan, WizardStep
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
