"""LangGraph node factory facade."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool
from langgraph.types import Command

from ..audit import AuditLog
from ..config.models import CommandPlanConfig, FilePatchConfig
from ..i18n import Translator, default_translator
from ..interfaces import LLMProvider
from ..services import BackgroundJobController, ClusterService, CommandService
from ..telemetry import TelemetryRecorder
from ..tools import ToolRuntimeLimits
from .analysis_node import make_analyze_result_node
from .confirm_node import make_confirm_node
from .events import RuntimeEventObserver
from .execute_node import make_execute_node
from .intent import make_parse_intent_node
from .plan_step_node import make_advance_plan_node
from .safety_nodes import make_safety_check_node
from .state import AgentState

Node = Callable[[AgentState], Awaitable[AgentState | Command[Any]]]
ToolEventObserver = Callable[[dict[str, Any]], Awaitable[None] | None]

__all__ = [
    "GraphDependencies",
    "make_advance_plan_node",
    "make_analyze_result_node",
    "make_confirm_node",
    "make_execute_node",
    "make_parse_intent_node",
    "make_safety_check_node",
]


@dataclass(frozen=True)
class GraphDependencies:
    provider: LLMProvider
    command_service: CommandService
    audit: AuditLog
    checkpointer: Any | None = None
    cluster_service: ClusterService | None = None
    background_jobs: BackgroundJobController | None = None
    tools: tuple[BaseTool, ...] = ()
    telemetry: TelemetryRecorder | None = None
    command_plan_config: CommandPlanConfig = field(default_factory=CommandPlanConfig)
    file_patch_config: FilePatchConfig = field(default_factory=FilePatchConfig)
    tool_observer: ToolEventObserver | None = None
    runtime_observer: RuntimeEventObserver | None = None
    tool_runtime_limits: ToolRuntimeLimits = field(default_factory=ToolRuntimeLimits)
    product_context: str = ""
    router_context: str = ""
    operating_manifest: str = ""
    parallel_direct_answer_tasks: int = 8
    translator: Translator = field(default_factory=default_translator)
