"""Runtime progress events for command plans."""

from __future__ import annotations

from ..runtime_events import RuntimeEventPhase, plan_legacy_event, plan_work_item_event
from ..turn_context import current_turn_context
from .events import RuntimeEventObserver, notify_event
from .plan_steps import command_plan_items
from .state import AgentState


async def notify_command_plan_progress(
    observer: RuntimeEventObserver | None,
    trace_id: str,
    state: AgentState,
    *,
    phase: RuntimeEventPhase | str = RuntimeEventPhase.UPDATED,
) -> None:
    """Publish active-view and legacy checklist progress for a command plan."""

    items = command_plan_items(state)
    if not items:
        return
    explanation = _command_plan_explanation(state)
    turn = current_turn_context()
    if turn is not None:
        await notify_event(
            observer,
            plan_work_item_event(
                thread_id=turn.thread_id,
                turn_id=turn.turn_id,
                trace_id=trace_id,
                phase=phase,
                explanation=explanation,
                items=items,
            ).to_event(),
        )
    await notify_event(
        observer,
        plan_legacy_event(
            trace_id=trace_id,
            phase=phase,
            explanation=explanation,
            items=items,
        ),
    )


def _command_plan_explanation(state: AgentState) -> str | None:
    plan = state.get("command_plan")
    if plan is None:
        return None
    return plan.goal
