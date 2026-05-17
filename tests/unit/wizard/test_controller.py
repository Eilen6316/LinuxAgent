"""Wizard controller state-machine tests."""

from __future__ import annotations

import pytest

from linuxagent.wizard.controller import WizardController
from linuxagent.wizard.models import WizardOption, WizardPlan, WizardStableState, WizardStep


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


def test_arrow_and_tab_navigation() -> None:
    controller = WizardController(_plan())

    controller.move_option(1)
    assert controller.option_focus_index == 1
    controller.next_step()
    assert controller.current_step_id == "extras"
    assert controller.option_focus_index == 0
    controller.previous_step()
    assert controller.current_step_id == "database"


def test_number_key_jumps_to_option() -> None:
    controller = WizardController(_plan())

    controller.focus_option_number(3)

    assert controller.option_focus_index == 2


def test_single_select_confirms_and_jumps_to_next_unconfirmed_step() -> None:
    controller = WizardController(_plan())

    controller.enter()

    assert controller.current_step_id == "extras"
    assert controller.answers["database"].selected_ids == ("postgres",)


def test_multi_enter_toggles_without_auto_jump() -> None:
    controller = WizardController(_plan())
    controller.next_step()

    controller.enter()
    controller.move_option(1)
    controller.enter()
    controller.move_option(-1)
    controller.enter()

    assert controller.current_step_id == "extras"
    assert controller.answers["extras"].selected_ids == ("nginx",)


def test_submit_gate_opens_only_after_all_steps_confirmed() -> None:
    controller = WizardController(_plan())

    controller.enter()
    controller.enter()
    controller.next_step()

    assert controller.is_submit_tab
    result = controller.enter()
    assert result is not None
    assert result.status == "submit"


def test_type_something_text_edit_commit_and_escape() -> None:
    controller = WizardController(_plan())
    controller.focus_option_number(4)

    controller.enter()
    assert controller.editing_text is True
    controller.append_text("custom-db")
    controller.commit_text()

    assert controller.answers["database"].text == "custom-db"
    assert controller.current_step_id == "extras"
    controller.focus_option_number(4)
    controller.start_text_edit()
    controller.append_text(" temporary")
    controller.escape()
    assert controller.editing_text is False


def test_text_edit_backspace_ctrl_u_and_empty_submit() -> None:
    controller = WizardController(_plan())
    controller.focus_option_number(4)
    controller.start_text_edit()

    controller.append_text("abc")
    controller.backspace_text()
    assert controller.text_buffer == "ab"
    controller.clear_text()
    assert controller.text_buffer == ""
    controller.commit_text()

    assert controller.editing_text is True
    assert "database" not in controller.answers


def test_text_answer_clears_selected_option_for_same_step() -> None:
    controller = WizardController(_plan())

    controller.enter()
    controller.previous_step()
    controller.focus_option_number(4)
    controller.start_text_edit()
    controller.append_text("外部数据库")
    controller.commit_text()

    assert controller.answers["database"].selected_ids == ()
    assert controller.answers["database"].text == "外部数据库"


def test_chat_about_this_returns_partial_context() -> None:
    controller = WizardController(_plan())
    controller.enter()
    controller.focus_option_number(5)

    result = controller.enter()

    assert result is not None
    assert result.status == "chat_requested"
    assert result.partial is True
    assert result.answers[0].step_id == "database"


def test_escape_cancels_outside_text_edit() -> None:
    controller = WizardController(_plan())

    result = controller.escape()

    assert result is not None
    assert result.status == "cancel"


def test_stable_state_round_trips_confirmed_answers() -> None:
    controller = WizardController(_plan())
    controller.enter()

    restored = WizardController.from_stable_state(_plan(), controller.stable_state())

    assert restored.answers["database"].selected_ids == ("postgres",)
    assert restored.current_step_id == "extras"
    assert restored.editing_text is False
    assert restored.text_buffer == ""


def test_stable_state_does_not_include_uncommitted_text() -> None:
    controller = WizardController(_plan())
    controller.focus_option_number(4)
    controller.start_text_edit()
    controller.append_text("temporary")

    stable = controller.stable_state()

    assert stable.answers == ()
    assert stable.current_step_id == "database"


def test_restore_stable_state_rejects_unknown_step() -> None:
    stable = WizardStableState(current_step_id="missing")

    with pytest.raises(ValueError, match="unknown current step id"):
        WizardController.from_stable_state(_plan(), stable)
