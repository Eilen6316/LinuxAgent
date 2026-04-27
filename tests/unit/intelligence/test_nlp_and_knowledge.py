"""NLP enhancer, cache, recommendation, and knowledge tests."""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from linuxagent.intelligence import (
    CommandLearner,
    EmbeddingCache,
    KnowledgeBase,
    KnowledgeDocument,
    NLPEnhancer,
    PatternAnalyzer,
    RecommendationEngine,
)
from linuxagent.interfaces import ExecutionResult


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    def _embed(self, text: str) -> list[float]:
        lower = text.lower()
        return [
            1.0 if any(word in lower for word in ("disk", "df", "space")) else 0.0,
            1.0 if any(word in lower for word in ("process", "ps", "cpu")) else 0.0,
            1.0 if any(word in lower for word in ("log", "journal", "error")) else 0.0,
        ]


async def test_nlp_enhancer_ranks_semantic_match() -> None:
    enhancer = NLPEnhancer(FakeEmbeddings())
    result = await enhancer.find_similar_commands(
        "show disk space",
        ["ps aux", "df -h", "journalctl -xe"],
        top_k=3,
    )
    assert result[0][0] == "df -h"


async def test_embedding_cache_uses_0600(tmp_path) -> None:
    cache = EmbeddingCache(tmp_path)
    enhancer = NLPEnhancer(FakeEmbeddings(), cache=cache)
    await enhancer.find_similar_commands("disk", ["df -h"], top_k=1)
    files = list(tmp_path.glob("*.json"))
    assert files
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in files)


async def test_recommendation_engine_uses_stats_and_similarity() -> None:
    learner = CommandLearner()
    learner.record("df -h", ExecutionResult("df -h", 0, "", "", 0.1))
    learner.record("ps aux", ExecutionResult("ps aux", 0, "", "", 0.1))
    engine = RecommendationEngine(learner, NLPEnhancer(FakeEmbeddings()))
    result = await engine.recommend("disk full", limit=1)
    assert result[0].command == "df -h"


async def test_knowledge_base_searches_documents() -> None:
    kb = KnowledgeBase(NLPEnhancer(FakeEmbeddings()))
    kb.add(KnowledgeDocument("disk", "Use df -h to inspect disk space", {"topic": "disk"}))
    kb.add(KnowledgeDocument("proc", "Use ps aux to inspect processes", {"topic": "process"}))
    result = await kb.search("disk usage", k=1)
    assert result[0].document.id == "disk"


def test_pattern_analyzer_flags_command_shape() -> None:
    result = PatternAnalyzer().analyze("python script.py")
    assert result.executable == "python"
    assert result.arg_count == 1
    assert result.is_interactive is True
