from collections.abc import Sequence

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.domain.reranker import Reranker

DEFAULT_RERANK_CANDIDATE_LIMIT = 10


class RerankedKnowledgeRetriever:
    """Reranks a bounded candidate set from an existing KnowledgeRetriever."""

    def __init__(
        self,
        *,
        candidate_retriever: KnowledgeRetriever,
        reranker: Reranker,
        candidate_limit: int = DEFAULT_RERANK_CANDIDATE_LIMIT,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")
        self._candidate_retriever = candidate_retriever
        self._reranker = reranker
        self._candidate_limit = candidate_limit

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        candidates = self._candidate_retriever.search(query, self._candidate_limit)
        reranked_candidates = self._reranker.rerank(query, candidates)
        _validate_reranked_candidates(candidates, reranked_candidates)
        return reranked_candidates[:limit]


def _validate_reranked_candidates(
    candidates: Sequence[KnowledgeRetrievalResult],
    reranked_candidates: Sequence[KnowledgeRetrievalResult],
) -> None:
    candidate_ids = tuple(candidate.chunk_id for candidate in candidates)
    reranked_ids = tuple(candidate.chunk_id for candidate in reranked_candidates)
    if len(set(reranked_ids)) != len(reranked_ids):
        raise ValueError("Reranker returned duplicate chunk_ids")
    if set(reranked_ids) != set(candidate_ids):
        raise ValueError(
            "Reranker must return exactly the supplied candidate chunk_ids"
        )
