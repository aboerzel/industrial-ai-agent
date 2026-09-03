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

    def search_documentation(self, query: str) -> DocumentationSearchResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")

        return DocumentationSearchResult(
            query=normalized_query,
            results=self._retriever.search(
                normalized_query,
                DEFAULT_DOCUMENTATION_RESULT_LIMIT,
            ),
        )
