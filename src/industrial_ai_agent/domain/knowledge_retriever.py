from typing import Protocol

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult


class KnowledgeRetriever(Protocol):
    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]: ...
