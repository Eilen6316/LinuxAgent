"""Routing and terminal response nodes for the LinuxAgent graph."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from ..interfaces import SafetyLevel
from .runbook_planning import has_next_runbook_step
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


async def route_after_execute(state: AgentState) -> str:
    if has_next_runbook_step(state):
        return "CONTINUE_RUNBOOK"
    return "ANALYZE"
