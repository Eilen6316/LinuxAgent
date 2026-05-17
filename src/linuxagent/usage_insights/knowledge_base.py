"""Small embedding-backed in-memory knowledge base."""

from __future__ import annotations

from dataclasses import dataclass

from .nlp_enhancer import NLPEnhancer


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    content: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class KnowledgeHit:
    document: KnowledgeDocument
    score: float


class KnowledgeBase:
    def __init__(self, enhancer: NLPEnhancer) -> None:
        self._enhancer = enhancer
        self._documents: list[KnowledgeDocument] = []

    def add(self, document: KnowledgeDocument) -> None:
        self._documents.append(document)

    async def search(self, query: str, k: int = 5) -> list[KnowledgeHit]:
        if not self._documents:
            return []
        candidates = [document.content for document in self._documents]
        scored = await self._enhancer.find_similar_commands(query, candidates, top_k=k)
        hits: list[KnowledgeHit] = []
        for content, score in scored:
            document = next(doc for doc in self._documents if doc.content == content)
            hits.append(KnowledgeHit(document=document, score=score))
        return hits

    def snapshot(self) -> list[KnowledgeDocument]:
        return list(self._documents)
