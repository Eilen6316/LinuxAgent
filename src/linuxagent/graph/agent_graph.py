"""Build the LangGraph command-processing state machine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .intent import make_parse_intent_node
from .nodes import (
    GraphDependencies,
    make_advance_runbook_node,
    make_analyze_result_node,
    make_confirm_node,
    make_execute_node,
    make_safety_check_node,
)
from .routing import (
    respond_block_node,
    respond_node,
    respond_refused_node,
    route_after_execute,
    route_by_safety,
)
from .state import AgentState

if TYPE_CHECKING:
    AgentGraph = CompiledStateGraph[AgentState, None, AgentState, AgentState]
else:
    AgentGraph = CompiledStateGraph


def build_agent_graph(deps: GraphDependencies) -> AgentGraph:
    graph = StateGraph(AgentState)
    graph.add_node(
        "parse_intent",
        _langgraph_node(
            make_parse_intent_node(
                deps.provider,
                cluster_service=deps.cluster_service,
                tools=deps.tools,
                telemetry=deps.telemetry,
                runbook_engine=deps.runbook_engine,
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
        "execute",
        _langgraph_node(
            make_execute_node(deps.command_service, deps.audit, deps.cluster_service, deps.telemetry)
        ),
    )
    graph.add_node("advance_runbook", _langgraph_node(make_advance_runbook_node()))
    graph.add_node("analyze", _langgraph_node(make_analyze_result_node(deps.provider, deps.telemetry)))
    graph.add_node("respond", _langgraph_node(respond_node))
    graph.add_node("respond_block", _langgraph_node(respond_block_node))
    graph.add_node("respond_refused", _langgraph_node(respond_refused_node))

    graph.add_edge(START, "parse_intent")
    graph.add_edge("parse_intent", "safety_check")
    graph.add_conditional_edges(
        "safety_check",
        route_by_safety,
        {"BLOCK": "respond_block", "CONFIRM": "confirm", "SAFE": "execute"},
    )
    graph.add_conditional_edges(
        "execute",
        route_after_execute,
        {"CONTINUE_RUNBOOK": "advance_runbook", "ANALYZE": "analyze"},
    )
    graph.add_edge("advance_runbook", "safety_check")
    graph.add_edge("analyze", "respond")
    graph.add_edge("respond", END)
    graph.add_edge("respond_block", END)
    graph.add_edge("respond_refused", END)
    return cast(AgentGraph, graph.compile(checkpointer=MemorySaver()))


def _langgraph_node(action: Any) -> Any:
    return action
