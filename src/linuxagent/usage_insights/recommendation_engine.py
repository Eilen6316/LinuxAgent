"""Command recommendations from usage statistics and semantic similarity."""

from __future__ import annotations

from dataclasses import dataclass

from .command_learner import CommandLearner
from .nlp_enhancer import NLPEnhancer


@dataclass(frozen=True)
class Recommendation:
    command: str
    score: float
    reason: str


class RecommendationEngine:
    def __init__(self, learner: CommandLearner, enhancer: NLPEnhancer) -> None:
        self._learner = learner
        self._enhancer = enhancer

    async def recommend(self, context: str, limit: int = 5) -> list[Recommendation]:
        candidates = [command for command, _ in self._learner.top_commands(limit=50)]
        if not candidates:
            return []
        similar = await self._enhancer.find_similar_commands(context, candidates, top_k=limit)
        recommendations: list[Recommendation] = []
        for command, semantic_score in similar:
            stats = self._learner.stats_for(command)
            usage_score = stats.success_rate if stats is not None else 0.0
            score = (semantic_score * 0.7) + (usage_score * 0.3)
            recommendations.append(
                Recommendation(
                    command=command,
                    score=score,
                    reason=f"semantic={semantic_score:.2f}, success={usage_score:.2f}",
                )
            )
        recommendations.sort(key=lambda item: item.score, reverse=True)
        return recommendations[:limit]
