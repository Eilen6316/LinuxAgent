"""Build the LangGraph command-processing state machine."""

from __future__ import annotations

from typing import Any, TypeAlias

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .file_patch_nodes import (
    make_apply_file_patch_node,
    make_file_patch_confirm_node,
    make_repair_file_patch_node,
)
from .intent import make_parse_intent_node
from .nodes import (
    GraphDependencies,
    make_advance_runbook_node,
    make_analyze_result_node,
    make_confirm_node,
    make_execute_node,
    make_safety_check_node,
)
from .replanning import make_repair_plan_node
from .routing import (
    respond_block_node,
    respond_node,
    respond_refused_node,
    route_after_execute,
    route_after_file_patch_apply,
    route_after_parse,
    route_by_safety,
)
from .state import AgentState

AgentGraph: TypeAlias = Any


def build_agent_graph(deps: GraphDependencies) -> AgentGraph:
    graph = StateGraph(AgentState)
    _add_graph_nodes(graph, deps)
    _add_graph_edges(graph)
    return graph.compile(checkpointer=MemorySaver())


def _add_graph_nodes(graph: Any, deps: GraphDependencies) -> None:
    graph.add_node(
        "parse_intent",
        _langgraph_node(
            make_parse_intent_node(
                deps.provider,
                cluster_service=deps.cluster_service,
                tools=deps.tools,
                telemetry=deps.telemetry,
                runbook_engine=deps.runbook_engine,
                tool_observer=deps.tool_observer,
            )
        ),
    )
    graph.add_node(
        "safety_check",
        _langgraph_node(
            make_safety_check_node(deps.command_service, deps.cluster_service, deps.telemetry)
        ),
    )
    graph.add_node(
        "confirm",
        _langgraph_node(make_confirm_node(deps.audit, deps.command_service, deps.telemetry)),
    )
    graph.add_node(
        "file_patch_confirm",
        _langgraph_node(make_file_patch_confirm_node(deps.audit, deps.file_patch_config)),
    )
    graph.add_node(
        "apply_file_patch",
        _langgraph_node(make_apply_file_patch_node(deps.audit, deps.file_patch_config)),
    )
    graph.add_node(
        "repair_file_patch",
        _langgraph_node(
            make_repair_file_patch_node(
                deps.provider,
                deps.file_patch_config,
                tools=deps.tools,
                telemetry=deps.telemetry,
                tool_observer=deps.tool_observer,
            )
        ),
    )
    graph.add_node(
        "execute",
        _langgraph_node(
            make_execute_node(
                deps.command_service, deps.audit, deps.cluster_service, deps.telemetry
            )
        ),
    )
    graph.add_node("advance_runbook", _langgraph_node(make_advance_runbook_node()))
    graph.add_node(
        "repair_plan", _langgraph_node(make_repair_plan_node(deps.provider, deps.telemetry))
    )
    graph.add_node(
        "analyze", _langgraph_node(make_analyze_result_node(deps.provider, deps.telemetry))
    )
    graph.add_node("respond", _langgraph_node(respond_node))
    graph.add_node("respond_block", _langgraph_node(respond_block_node))
    graph.add_node("respond_refused", _langgraph_node(respond_refused_node))


def _add_graph_edges(graph: Any) -> None:
    graph.add_edge(START, "parse_intent")
    graph.add_conditional_edges(
        "parse_intent",
        route_after_parse,
        {
            "PATCH_CONFIRM": "file_patch_confirm",
            "RESPOND": "respond",
            "SAFETY": "safety_check",
        },
    )
    graph.add_conditional_edges(
        "safety_check",
        route_by_safety,
        {"BLOCK": "respond_block", "CONFIRM": "confirm", "SAFE": "execute"},
    )
    graph.add_conditional_edges(
        "execute",
        route_after_execute,
        {
            "CONTINUE_RUNBOOK": "advance_runbook",
            "REPAIR_PLAN": "repair_plan",
            "ANALYZE": "analyze",
        },
    )
    graph.add_edge("advance_runbook", "safety_check")
    graph.add_edge("repair_plan", "safety_check")
    graph.add_conditional_edges(
        "apply_file_patch",
        route_after_file_patch_apply,
        {"REPAIR_FILE_PATCH": "repair_file_patch", "ANALYZE": "analyze"},
    )
    graph.add_edge("analyze", "respond")
    graph.add_edge("respond", END)
    graph.add_edge("respond_block", END)
    graph.add_edge("respond_refused", END)


def _langgraph_node(action: Any) -> Any:
    return action
