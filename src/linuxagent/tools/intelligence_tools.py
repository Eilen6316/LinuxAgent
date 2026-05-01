"""LangChain tools for Intelligence capabilities."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from ..intelligence import (
    KnowledgeBase,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)
from ..sandbox import SandboxProfile
from .sandbox import ToolSandboxSpec, attach_tool_sandbox

INTELLIGENCE_TOOL_TIMEOUT_SECONDS = 5.0
INTELLIGENCE_TOOL_MAX_OUTPUT_CHARS = 20000


def make_command_recommendations_tool(engine: RecommendationEngine) -> BaseTool:
    @tool
    async def get_command_recommendations(context: str, limit: int = 5) -> list[str]:
        """Suggest relevant commands based on context and usage history."""
        recommendations = await engine.recommend(context, limit=limit)
        return [f"{item.command} ({item.reason})" for item in recommendations]

    return _attach_intelligence_sandbox(get_command_recommendations)


def make_similar_commands_tool(enhancer: NLPEnhancer, candidates: list[str]) -> BaseTool:
    @tool
    async def get_similar_commands(query: str, top_k: int = 5) -> list[str]:
        """Return commands semantically similar to the query."""
        scored = await enhancer.find_similar_commands(query, candidates, top_k=top_k)
        return [f"{command} score={score:.3f}" for command, score in scored]

    return _attach_intelligence_sandbox(get_similar_commands)


def make_knowledge_base_tool(kb: KnowledgeBase) -> BaseTool:
    @tool
    async def search_knowledge_base(query: str, k: int = 5) -> list[str]:
        """Search the Linux operations knowledge base."""
        hits = await kb.search(query, k=k)
        return [f"{hit.document.id}: {hit.document.content}" for hit in hits]

    return _attach_intelligence_sandbox(search_knowledge_base)


def make_pattern_analyzer_tool(analyzer: PatternAnalyzer) -> BaseTool:
    @tool
    def analyze_command_pattern(command: str) -> dict[str, object]:
        """Analyze command shape, destructiveness, and interactivity."""
        result = analyzer.analyze(command)
        return {
            "command": result.command,
            "executable": result.executable,
            "arg_count": result.arg_count,
            "is_destructive": result.is_destructive,
            "is_interactive": result.is_interactive,
        }

    return _attach_intelligence_sandbox(analyze_command_pattern, network_access=False)


def build_intelligence_tools(
    *,
    recommendation_engine: RecommendationEngine,
    knowledge_base: KnowledgeBase,
    pattern_analyzer: PatternAnalyzer,
    nlp_enhancer: NLPEnhancer,
    command_candidates: list[str],
) -> list[BaseTool]:
    return [
        make_command_recommendations_tool(recommendation_engine),
        make_knowledge_base_tool(knowledge_base),
        make_pattern_analyzer_tool(pattern_analyzer),
        make_similar_commands_tool(nlp_enhancer, command_candidates),
    ]


def _attach_intelligence_sandbox(tool: BaseTool, *, network_access: bool = True) -> BaseTool:
    return attach_tool_sandbox(
        tool,
        ToolSandboxSpec(
            profile=SandboxProfile.READ_ONLY,
            max_output_chars=INTELLIGENCE_TOOL_MAX_OUTPUT_CHARS,
            timeout_seconds=INTELLIGENCE_TOOL_TIMEOUT_SECONDS,
            network_access=network_access,
        ),
    )
