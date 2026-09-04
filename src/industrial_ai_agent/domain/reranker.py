from collections.abc import Sequence
from typing import Protocol

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult


class Reranker(Protocol):
    """Provider-independent relevance ranking for an already retrieved candidate set."""

    def rerank(
        self,
        query: str,
        candidates: Sequence[KnowledgeRetrievalResult],
    ) -> tuple[KnowledgeRetrievalResult, ...]: ...
