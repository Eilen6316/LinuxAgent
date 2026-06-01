"""Graph runtime construction helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool

from ..audit import AuditLog
from ..config.models import AppConfig
from ..event_replay import TurnReplaySnapshot
from ..graph import GraphDependencies, GraphRuntime, build_agent_graph
from ..graph.agent_graph import AgentGraph
from ..graph.checkpoint import PersistentMemorySaver
from ..i18n import Translator
from ..interfaces import LLMProvider
from ..services import BackgroundJobController, ClusterService, CommandService
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits


def build_graph(
    config: AppConfig,
    *,
    provider: LLMProvider,
    command_service: CommandService,
    audit: AuditLog,
    checkpointer: PersistentMemorySaver,
    cluster_service: ClusterService,
    background_jobs: BackgroundJobController,
    tools: tuple[BaseTool, ...],
    telemetry: TelemetryRecorder,
    tool_observer: Callable[[dict[str, Any]], Any],
    runtime_observer: Callable[[dict[str, Any]], Any],
    tool_runtime_limits: ToolRuntimeLimits,
    product_context: str,
    router_context: str,
    operating_manifest: str,
    translator: Translator,
) -> AgentGraph:
    return build_agent_graph(
        GraphDependencies(
            provider=provider,
            command_service=command_service,
            audit=audit,
            checkpointer=checkpointer,
            cluster_service=cluster_service,
            background_jobs=background_jobs,
            tools=tools,
            telemetry=telemetry,
            command_plan_config=config.command_plan,
            file_patch_config=config.file_patch,
            tool_observer=tool_observer,
            runtime_observer=runtime_observer,
            tool_runtime_limits=tool_runtime_limits,
            product_context=product_context,
            router_context=router_context,
            operating_manifest=operating_manifest,
            parallel_direct_answer_tasks=config.command_plan.parallel_direct_answer_tasks,
            translator=translator,
        )
    )


def build_graph_runtime(
    graph: AgentGraph,
    runtime_observer: Callable[[dict[str, Any]], Any] | None = None,
    replay_snapshot_provider: Callable[[str], TurnReplaySnapshot | None] | None = None,
) -> GraphRuntime:
    return GraphRuntime(
        graph,
        runtime_observer=runtime_observer,
        replay_snapshot_provider=replay_snapshot_provider,
    )
