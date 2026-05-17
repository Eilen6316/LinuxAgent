"""Per-turn app state construction tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from linuxagent.app.graph_config import graph_config
from linuxagent.app.turn_state import new_turn_state


async def test_new_turn_state_carries_wizard_failure_guard() -> None:
    state = await new_turn_state(
        _Graph({"wizard_attempted": True, "wizard_failed_reason": "parse_failed"}),
        graph_config("thread"),
        "continue",
        history=[],
        command_permissions=(),
        prompt_cache_thread_id=None,
        ui_interactive=True,
    )

    assert state["wizard_attempted"] is True
    assert state["wizard_failed_reason"] == "parse_failed"


async def test_new_turn_state_does_not_carry_completed_wizard_guard() -> None:
    state = await new_turn_state(
        _Graph(
            {
                "wizard_attempted": True,
                "wizard_completed": True,
                "wizard_result": {"status": "submit"},
            }
        ),
        graph_config("thread"),
        "continue",
        history=[],
        command_permissions=(),
        prompt_cache_thread_id=None,
        ui_interactive=True,
    )

    assert state["wizard_attempted"] is False
    assert state["wizard_failed_reason"] is None


async def test_new_turn_state_carries_non_submit_wizard_guard_with_saved_plan() -> None:
    state = await new_turn_state(
        _Graph(
            {
                "wizard_attempted": True,
                "wizard_plan": {"title": "Needs input", "steps": []},
                "wizard_result": {"status": "cancel"},
            }
        ),
        graph_config("thread"),
        "continue",
        history=[],
        command_permissions=(),
        prompt_cache_thread_id=None,
        ui_interactive=True,
    )

    assert state["wizard_attempted"] is True
    assert state["wizard_result"] == {"status": "cancel"}


class _Graph:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    async def aget_state(self, config: Any) -> Any:
        del config
        return SimpleNamespace(values=self._values)
