"""Intelligence modules: learning, embeddings, recommendations, knowledge, patterns."""

from __future__ import annotations

from .command_learner import CommandLearner, CommandStats
from .context_manager import ContextManager
from .embedding_cache import EmbeddingCache
from .knowledge_base import KnowledgeBase, KnowledgeDocument, KnowledgeHit
from .nlp_enhancer import NLPEnhancer
from .pattern_analyzer import PatternAnalysis, PatternAnalyzer
from .recommendation_engine import Recommendation, RecommendationEngine

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
