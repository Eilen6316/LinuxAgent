"""Embedding-backed semantic helpers."""

from __future__ import annotations

import math

from langchain_core.embeddings import Embeddings

from .embedding_cache import EmbeddingCache


class NLPEnhancer:
    def __init__(self, embeddings: Embeddings, cache: EmbeddingCache | None = None) -> None:
        self._embeddings = embeddings
        self._cache = cache

    async def find_similar_commands(
        self,
        query: str,
        candidates: list[str],
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        if not candidates:
            return []
        query_emb = await self._embed_query(query)
        cand_embs = [await self._embed_document(candidate) for candidate in candidates]
        scored = [
            (candidate, _cosine(query_emb, embedding))
            for candidate, embedding in zip(candidates, cand_embs, strict=True)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    async def _embed_query(self, text: str) -> list[float]:
        cached = self._cache.get(text) if self._cache is not None else None
        if cached is not None:
            return cached
        embedding = [float(value) for value in await self._embeddings.aembed_query(text)]
        if self._cache is not None:
            self._cache.set(text, embedding)
        return embedding

    async def _embed_document(self, text: str) -> list[float]:
        cached = self._cache.get(text) if self._cache is not None else None
        if cached is not None:
            return cached
        embedding = [float(value) for value in (await self._embeddings.aembed_documents([text]))[0]]
        if self._cache is not None:
            self._cache.set(text, embedding)
        return embedding


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
