from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever

DEFAULT_DOCUMENTATION_RESULT_LIMIT = 3


class DocumentationSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    results: tuple[KnowledgeRetrievalResult, ...]


class DocumentationSearchCapability:
    def __init__(self, retriever: KnowledgeRetriever) -> None:
        self._retriever = retriever

    def search_documentation(
        self,
        query: str,
        top_k: int = DEFAULT_DOCUMENTATION_RESULT_LIMIT,
    ) -> DocumentationSearchResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        return DocumentationSearchResult(
            query=normalized_query,
            results=self._retriever.search(normalized_query, top_k),
        )
