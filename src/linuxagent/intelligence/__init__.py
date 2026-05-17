"""Compatibility exports for the renamed usage insights package."""

from __future__ import annotations

from ..usage_insights import (
    CommandLearner,
    CommandStats,
    ContextManager,
    EmbeddingCache,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeHit,
    NLPEnhancer,
    PatternAnalysis,
    PatternAnalyzer,
    Recommendation,
    RecommendationEngine,
)

__all__ = [
    "CommandLearner",
    "CommandStats",
    "ContextManager",
    "EmbeddingCache",
    "KnowledgeBase",
    "KnowledgeDocument",
    "KnowledgeHit",
    "NLPEnhancer",
    "PatternAnalysis",
    "PatternAnalyzer",
    "Recommendation",
    "RecommendationEngine",
]
