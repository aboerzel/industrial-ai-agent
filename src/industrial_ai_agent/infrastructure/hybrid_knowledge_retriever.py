from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever

DEFAULT_RRF_RANK_CONSTANT = 60


@dataclass(frozen=True, slots=True)
class _FusedRank:
    chunk_id: str
    score: float


class HybridKnowledgeRetriever:
    """Fuses independent lexical and semantic rankings with reciprocal rank fusion."""

    def __init__(
        self,
        chunks: Iterable[KnowledgeRetrievalResult],
        *,
        bm25_retriever: KnowledgeRetriever,
        semantic_retriever: KnowledgeRetriever,
        rank_constant: int = DEFAULT_RRF_RANK_CONSTANT,
    ) -> None:
        indexed_chunks = tuple(chunks)
        self._chunks_by_id = {chunk.chunk_id: chunk for chunk in indexed_chunks}
        if not self._chunks_by_id:
            raise ValueError("Hybrid index must contain at least one chunk")
        if len(self._chunks_by_id) != len(indexed_chunks):
            raise ValueError("Hybrid index must not contain duplicate chunk_ids")
        if rank_constant < 1:
            raise ValueError("rank_constant must be at least 1")

        self._bm25_retriever = bm25_retriever
        self._semantic_retriever = semantic_retriever
        self._rank_constant = rank_constant
        # The frozen corpus is small, so both component rankings include every chunk.
        self._candidate_limit = len(self._chunks_by_id)

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        rankings = (
            self._bm25_retriever.search(query, self._candidate_limit),
            self._semantic_retriever.search(query, self._candidate_limit),
        )
        fused_ranks = reciprocal_rank_fusion(
            rankings,
            rank_constant=self._rank_constant,
        )
        return tuple(
            self._result_for_fused_rank(fused_rank)
            for fused_rank in fused_ranks[:limit]
        )

    def _result_for_fused_rank(
        self,
        fused_rank: _FusedRank,
    ) -> KnowledgeRetrievalResult:
        try:
            chunk = self._chunks_by_id[fused_rank.chunk_id]
        except KeyError as error:
            raise ValueError(
                "Component retriever returned an unknown chunk_id: "
                f"{fused_rank.chunk_id}"
            ) from error
        return chunk.model_copy(update={"relevance_score": fused_rank.score})


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[KnowledgeRetrievalResult]],
    *,
    rank_constant: int = DEFAULT_RRF_RANK_CONSTANT,
) -> tuple[_FusedRank, ...]:
    """Fuse rankings using only one-based positions, never component raw scores.

    For each chunk ``d``, the fused score is
    ``sum(1 / (rank_constant + rank_i(d)))`` over all component rankings that
    contain it. Equal fused scores use ``chunk_id`` as the stable tie-breaker.
    """
    if rank_constant < 1:
        raise ValueError("rank_constant must be at least 1")

    fused_scores: dict[str, float] = {}
    for ranking in rankings:
        seen_chunk_ids: set[str] = set()
        for rank, result in enumerate(ranking, start=1):
            if result.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(result.chunk_id)
            fused_scores[result.chunk_id] = fused_scores.get(result.chunk_id, 0.0) + (
                1.0 / (rank_constant + rank)
            )

    return tuple(
        _FusedRank(chunk_id=chunk_id, score=score)
        for chunk_id, score in sorted(
            fused_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
    )
