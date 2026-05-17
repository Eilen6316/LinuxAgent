"""Build per-turn graph state for the app coordinator."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from ..graph import initial_state
from ..graph.state import AgentState
from ..interfaces import CommandSource


async def new_turn_state(
    graph: Any,
    config: RunnableConfig,
    user_input: str,
    *,
    history: list[BaseMessage],
    command_permissions: tuple[str, ...],
    prompt_cache_thread_id: str | None,
    ui_interactive: bool,
) -> AgentState:
    state = initial_state(
        user_input,
        source=CommandSource.USER,
        history=history,
        command_permissions=command_permissions,
        thread_id=prompt_cache_thread_id,
        ui_interactive=ui_interactive,
    )
    snapshot = await graph.aget_state(config)
    values = getattr(snapshot, "values", {})
    if isinstance(values, dict):
        _carry_wizard_guard(state, values)
    return state


def _carry_wizard_guard(state: AgentState, values: dict[str, Any]) -> None:
    if not _should_carry_wizard_guard(values):
        return
    state["wizard_attempted"] = values.get("wizard_attempted") is True
    failed_reason = values.get("wizard_failed_reason")
    if failed_reason in {"parse_failed", "provider_failed", "non_tty", "loop_guard"}:
        state["wizard_failed_reason"] = failed_reason
    result = values.get("wizard_result")
    if isinstance(result, dict):
        state["wizard_result"] = result
    stable_state = values.get("wizard_stable_state")
    if isinstance(stable_state, dict):
        state["wizard_stable_state"] = stable_state


def _should_carry_wizard_guard(values: dict[str, Any]) -> bool:
    if values.get("wizard_completed") is True:
        return False
    result = values.get("wizard_result")
    if isinstance(result, dict):
        return result.get("status") != "submit"
    if values.get("wizard_plan") is not None:
        return False
    return values.get("wizard_failed_reason") is not None
