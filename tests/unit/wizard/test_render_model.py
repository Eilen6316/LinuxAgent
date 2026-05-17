"""Wizard render-model tests."""

from __future__ import annotations

from linuxagent.wizard.controller import WizardController
from linuxagent.wizard.models import WizardOption, WizardPlan, WizardStep
from linuxagent.wizard.render_model import build_render_model


def _option(option_id: str) -> WizardOption:
    return WizardOption(id=option_id, label=option_id.title(), description="说明")


def _plan() -> WizardPlan:
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
                id="extras",
                title="附加组件",
                kind="multi",
                options=(_option("redis"), _option("nginx"), _option("backup")),
            ),
        ),
    )


def test_render_model_tab_and_footer_text_are_stable() -> None:
    model = build_render_model(WizardController(_plan()))

    assert model.user_intent == "部署服务"
    assert model.tabs[0].marker == "■"
    assert model.tabs[1].marker == "□"
    assert model.tabs[-1].label == "Submit"
    assert model.footer_text == "Enter to select · Tab/Arrow keys to navigate · Esc to cancel"


def test_render_model_current_title_uses_brackets() -> None:
    model = build_render_model(WizardController(_plan()))

    assert model.current_title == "[数据库]"


def test_render_model_single_and_multi_rows() -> None:
    controller = WizardController(_plan())
    single = build_render_model(controller)
    controller.next_step()
    multi = build_render_model(controller)

    assert single.option_rows[0].multi is False
    assert multi.option_rows[0].multi is True


def test_render_model_includes_fixed_tail_items_in_order() -> None:
    model = build_render_model(WizardController(_plan()))

    assert model.option_rows[-2].label == "Type something"
    assert model.option_rows[-1].label == "Chat about this"
