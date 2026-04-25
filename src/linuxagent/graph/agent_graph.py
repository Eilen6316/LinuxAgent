"""Build the LangGraph command-processing state machine."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .nodes import (
    GraphDependencies,
    make_analyze_result_node,
    make_confirm_node,
    make_execute_node,
    make_parse_intent_node,
    make_safety_check_node,
    respond_block_node,
    respond_node,
    respond_refused_node,
    route_by_safety,
)
from .state import AgentState


def build_agent_graph(deps: GraphDependencies) -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    graph.add_node(
        "parse_intent",
        make_parse_intent_node(
            deps.provider,
            cluster_service=deps.cluster_service,
            tools=deps.tools,
            telemetry=deps.telemetry,
        ),
    )
    graph.add_node(
        "safety_check",
        make_safety_check_node(deps.command_service, deps.cluster_service, deps.telemetry),
    )
    graph.add_node("confirm", make_confirm_node(deps.audit, deps.command_service, deps.telemetry))
    graph.add_node(
        "execute",
        make_execute_node(deps.command_service, deps.audit, deps.cluster_service, deps.telemetry),
    )
    graph.add_node("analyze", make_analyze_result_node(deps.provider, deps.telemetry))
    graph.add_node("respond", respond_node)
    graph.add_node("respond_block", respond_block_node)
    graph.add_node("respond_refused", respond_refused_node)

    graph.add_edge(START, "parse_intent")
    graph.add_edge("parse_intent", "safety_check")
    graph.add_conditional_edges(
        "safety_check",
        route_by_safety,
        {"BLOCK": "respond_block", "CONFIRM": "confirm", "SAFE": "execute"},
    )
    graph.add_edge("execute", "analyze")
    graph.add_edge("analyze", "respond")
    graph.add_edge("respond", END)
    graph.add_edge("respond_block", END)
    graph.add_edge("respond_refused", END)
    return graph.compile(checkpointer=MemorySaver())
