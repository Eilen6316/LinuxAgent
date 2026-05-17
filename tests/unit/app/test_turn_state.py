"""Per-turn app state construction tests."""

from __future__ import annotations

from linuxagent.app.turn_state import new_turn_state


def test_new_turn_state_carries_wizard_failure_guard() -> None:
    state = new_turn_state(
        "continue",
        history=[],
        command_permissions=(),
        prompt_cache_thread_id=None,
        ui_interactive=True,
        previous_values={"wizard_attempted": True, "wizard_failed_reason": "parse_failed"},
    )

    assert state["wizard_attempted"] is True
    assert state["wizard_failed_reason"] == "parse_failed"


def test_new_turn_state_does_not_carry_completed_wizard_guard() -> None:
    state = new_turn_state(
        "continue",
        history=[],
        command_permissions=(),
        prompt_cache_thread_id=None,
        ui_interactive=True,
        previous_values={
            "wizard_attempted": True,
            "wizard_completed": True,
            "wizard_result": {"status": "submit"},
        },
    )

    assert state["wizard_attempted"] is False
    assert state["wizard_failed_reason"] is None


def test_new_turn_state_carries_non_submit_wizard_guard_with_saved_plan() -> None:
    state = new_turn_state(
        "continue",
        history=[],
        command_permissions=(),
        prompt_cache_thread_id=None,
        ui_interactive=True,
        previous_values={
            "wizard_attempted": True,
            "wizard_plan": {"title": "Needs input", "steps": []},
            "wizard_result": {"status": "cancel"},
        },
    )

    assert state["wizard_attempted"] is True
    assert state["wizard_result"] == {"status": "cancel"}
