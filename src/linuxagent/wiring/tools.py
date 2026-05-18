"""Tool catalog construction helpers."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from ..config.models import AppConfig
from ..executors import LinuxCommandExecutor
from ..product_context import product_capability_context
from ..tools import (
    ToolCatalogReport,
    ToolRuntimeLimits,
    build_intelligence_tools,
    build_system_tools,
    build_workspace_tools,
    compact_tool_catalog_summary,
    inspect_tool_catalog,
)
from ..usage_insights import (
    CommandLearner,
    KnowledgeBase,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)


def build_system_tool_list(config: AppConfig, executor: LinuxCommandExecutor) -> list[BaseTool]:
    return build_system_tools(
        executor,
        allowed_log_roots=_allowed_log_roots(config.log_analysis.default_log_paths),
        monitoring_config=config.monitoring,
        tool_config=config.sandbox.tools,
        enable_execute_command=config.sandbox.tools.enable_execute_command,
    )


def intelligence_tools_enabled(config: AppConfig) -> bool:
    return config.intelligence.enabled and config.intelligence.tools_enabled is True


def build_intelligence_tool_list(
    config: AppConfig,
    *,
    learner: CommandLearner,
    recommendation_engine: RecommendationEngine,
    knowledge_base: KnowledgeBase,
    pattern_analyzer: PatternAnalyzer,
    nlp_enhancer: NLPEnhancer,
) -> list[BaseTool]:
    if not intelligence_tools_enabled(config):
        return []
    command_candidates = [command for command, _ in learner.top_commands(limit=50)]
    if not command_candidates:
        command_candidates = list(config.intelligence.default_command_candidates)
    return build_intelligence_tools(
        recommendation_engine=recommendation_engine,
        knowledge_base=knowledge_base,
        pattern_analyzer=pattern_analyzer,
        nlp_enhancer=nlp_enhancer,
        command_candidates=command_candidates,
    )


def build_tool_catalog(
    config: AppConfig,
    *,
    system_tools: list[BaseTool],
    intelligence_tools: list[BaseTool],
    network_tools: list[BaseTool],
) -> ToolCatalogReport:
    return inspect_tool_catalog(
        [
            *system_tools,
            *build_workspace_tools(config.file_patch, config.sandbox.tools),
            *network_tools,
            *intelligence_tools,
        ]
    )


def build_tool_runtime_limits(config: AppConfig) -> ToolRuntimeLimits:
    tools = config.sandbox.tools
    return ToolRuntimeLimits(
        max_rounds=tools.max_rounds,
        timeout_seconds=tools.timeout_seconds,
        max_output_chars=tools.max_output_chars,
        max_total_output_chars=tools.max_total_output_chars,
    )


def build_product_context(config: AppConfig, catalog: ToolCatalogReport) -> str:
    return product_capability_context(
        provider=config.api.provider.value,
        model=config.api.model,
        tool_names=tuple(item.name for item in catalog.items),
        tool_catalog=compact_tool_catalog_summary(catalog),
    )


def _allowed_log_roots(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple({path.parent for path in paths})
