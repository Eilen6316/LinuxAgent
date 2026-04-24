"""Intelligence tool registration tests."""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from linuxagent.intelligence import (
    CommandLearner,
    KnowledgeBase,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)
from linuxagent.interfaces import ExecutionResult
from linuxagent.tools import build_intelligence_tools


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "df" in text else [0.0, 1.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0] if "disk" in text else [0.0, 1.0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


async def test_build_intelligence_tools_registers_all() -> None:
    learner = CommandLearner()
    learner.record("df -h", ExecutionResult("df -h", 0, "", "", 0.1))
    enhancer = NLPEnhancer(FakeEmbeddings())
    tools = build_intelligence_tools(
        recommendation_engine=RecommendationEngine(learner, enhancer),
        knowledge_base=KnowledgeBase(enhancer),
        pattern_analyzer=PatternAnalyzer(),
        nlp_enhancer=enhancer,
        command_candidates=["df -h", "ps aux"],
    )
    names = {tool.name for tool in tools}
    assert names == {
        "get_command_recommendations",
        "search_knowledge_base",
        "analyze_command_pattern",
        "get_similar_commands",
    }
    similar = await next(tool for tool in tools if tool.name == "get_similar_commands").ainvoke(
        {"query": "disk", "top_k": 1}
    )
    assert similar[0].startswith("df -h")
