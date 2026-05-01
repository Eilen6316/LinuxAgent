"""Routing and terminal response nodes for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage

from ..interfaces import SafetyLevel
from .file_patch_nodes import should_repair_file_patch
from .replanning import should_repair_plan
from .runbook_planning import has_next_plan_step
from .state import AgentState


async def respond_block_node(state: AgentState) -> AgentState:
    reason = state.get("safety_reason") or "command blocked by safety policy"
    return {"messages": [AIMessage(content=f"已阻止执行：{reason}")]}


async def respond_refused_node(state: AgentState) -> AgentState:
    command = state.get("pending_command") or ""
    return {"messages": [AIMessage(content=f"已拒绝执行：{command}")]}


async def respond_node(state: AgentState) -> AgentState:
    if state.get("messages"):
        return {}
    return {"messages": [AIMessage(content="操作已完成。")]}


async def route_by_safety(state: AgentState) -> str:
    level = state.get("safety_level")
    if level is SafetyLevel.BLOCK:
        return "BLOCK"
    if level is SafetyLevel.CONFIRM:
        return "CONFIRM"
    return "SAFE"


async def route_after_parse(state: AgentState) -> str:
    if state.get("direct_response"):
        return "RESPOND"
    if state.get("file_patch_plan") is not None:
        return "PATCH_CONFIRM"
    return "SAFETY"


async def route_after_execute(state: AgentState) -> str:
    if has_next_plan_step(state):
        return "CONTINUE_RUNBOOK"
    if should_repair_plan(state):
        return "REPAIR_PLAN"
    return "ANALYZE"


def make_route_after_execute(max_repair_attempts: int) -> Callable[[AgentState], Awaitable[str]]:
    async def route(state: AgentState) -> str:
        if has_next_plan_step(state):
            return "CONTINUE_RUNBOOK"
        if should_repair_plan(state, max_repair_attempts=max_repair_attempts):
            return "REPAIR_PLAN"
        return "ANALYZE"

    return route


async def route_after_file_patch_apply(state: AgentState) -> str:
    if should_repair_file_patch(state):
        return "REPAIR_FILE_PATCH"
    return "ANALYZE"
