"""Routing and terminal response nodes for the LinuxAgent graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage

from ..i18n import Translator, default_translator
from ..interfaces import SafetyLevel
from .file_patch_nodes import should_repair_file_patch
from .plan_steps import has_next_plan_step
from .replanning import should_repair_plan
from .state import AgentState


def make_respond_block_node(
    translator: Translator | None = None,
) -> Callable[[AgentState], Awaitable[AgentState]]:
    tr = translator or default_translator()

    async def respond_block(state: AgentState) -> AgentState:
        reason = state.get("safety_reason") or "command blocked by safety policy"
        if reason == default_translator().t("graph.argv_retry_exhausted"):
            reason = tr.t("graph.argv_retry_exhausted")
        return {"messages": [AIMessage(content=tr.t("graph.blocked", reason=reason))]}

    return respond_block


def make_respond_refused_node(
    translator: Translator | None = None,
) -> Callable[[AgentState], Awaitable[AgentState]]:
    tr = translator or default_translator()

    async def respond_refused(state: AgentState) -> AgentState:
        command = state.get("pending_command") or ""
        return {"messages": [AIMessage(content=tr.t("graph.refused", command=command))]}

    return respond_refused


def make_respond_node(
    translator: Translator | None = None,
) -> Callable[[AgentState], Awaitable[AgentState]]:
    tr = translator or default_translator()

    async def respond(state: AgentState) -> AgentState:
        if state.get("messages"):
            return {}
        return {"messages": [AIMessage(content=tr.t("graph.done"))]}

    return respond


async def respond_block_node(state: AgentState) -> AgentState:
    return await make_respond_block_node()(state)


async def respond_refused_node(state: AgentState) -> AgentState:
    return await make_respond_refused_node()(state)


async def respond_node(state: AgentState) -> AgentState:
    return await make_respond_node()(state)


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
    if state.get("wizard_completed"):
        return "SAFETY"
    if state.get("wizard_context") and state.get("wizard_result") is None:
        return "WIZARD"
    return "SAFETY"


async def route_after_execute(state: AgentState) -> str:
    if has_next_plan_step(state):
        return "CONTINUE_PLAN"
    if should_repair_plan(state):
        return "REPAIR_PLAN"
    return "ANALYZE"


def make_route_after_execute(max_repair_attempts: int) -> Callable[[AgentState], Awaitable[str]]:
    async def route(state: AgentState) -> str:
        if has_next_plan_step(state):
            return "CONTINUE_PLAN"
        if should_repair_plan(state, max_repair_attempts=max_repair_attempts):
            return "REPAIR_PLAN"
        return "ANALYZE"

    return route


async def route_after_file_patch_apply(state: AgentState) -> str:
    if should_repair_file_patch(state):
        return "REPAIR_FILE_PATCH"
    if state.get("file_patch_verification_pending"):
        return "VERIFY_FILE_PATCH"
    return "ANALYZE"
