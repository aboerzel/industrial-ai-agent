from collections.abc import Sequence

import pytest

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.infrastructure.hybrid_knowledge_retriever import (
    DEFAULT_RRF_RANK_CONSTANT,
    HybridKnowledgeRetriever,
    reciprocal_rank_fusion,
)


def chunk(
    chunk_id: str,
    *,
    score: float | None = None,
) -> KnowledgeRetrievalResult:
    document_id = chunk_id.split("::", maxsplit=1)[0]
    return KnowledgeRetrievalResult(
        content=f"Content for {chunk_id}",
        document_id=document_id,
        source=f"{document_id}.md",
        chunk_id=chunk_id,
        metadata={"title": chunk_id},
        relevance_score=score,
    )


class StaticKnowledgeRetriever:
    def __init__(self, results: Sequence[KnowledgeRetrievalResult]) -> None:
        self._results = tuple(results)
        self.requests: list[tuple[str, int]] = []

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        self.requests.append((query, limit))
        return self._results[:limit]


def test_rrf_fuses_shared_and_single_source_chunks_by_rank() -> None:
    fused = reciprocal_rank_fusion(
        (
            (chunk("a::chunk-001", score=0.01), chunk("b::chunk-001", score=99)),
            (chunk("b::chunk-001", score=0.001), chunk("c::chunk-001", score=42)),
        )
    )

    assert [item.chunk_id for item in fused] == [
        "b::chunk-001",
        "a::chunk-001",
        "c::chunk-001",
    ]
    assert fused[0].score == pytest.approx(
        1 / (DEFAULT_RRF_RANK_CONSTANT + 2) + 1 / (DEFAULT_RRF_RANK_CONSTANT + 1)
    )
    assert fused[1].score == pytest.approx(1 / (DEFAULT_RRF_RANK_CONSTANT + 1))
    assert fused[2].score == pytest.approx(1 / (DEFAULT_RRF_RANK_CONSTANT + 2))


def test_rrf_uses_stable_chunk_id_tie_breaking() -> None:
    fused = reciprocal_rank_fusion(
        (
            (chunk("b::chunk-001"),),
            (chunk("a::chunk-001"),),
        )
    )

    assert [item.chunk_id for item in fused] == ["a::chunk-001", "b::chunk-001"]


def test_rrf_ignores_component_raw_scores() -> None:
    first = reciprocal_rank_fusion(
        (
            (chunk("a::chunk-001", score=1_000_000), chunk("b::chunk-001", score=0)),
            (chunk("b::chunk-001", score=1_000_000), chunk("a::chunk-001", score=0)),
        )
    )
    second = reciprocal_rank_fusion(
        (
            (chunk("a::chunk-001", score=0), chunk("b::chunk-001", score=1_000_000)),
            (chunk("b::chunk-001", score=0), chunk("a::chunk-001", score=1_000_000)),
        )
    )

    assert first == second


def test_hybrid_retriever_preserves_provenance_and_enforces_top_k() -> None:
    chunks = (
        chunk("a::chunk-001"),
        chunk("b::chunk-001"),
        chunk("c::chunk-001"),
    )
    bm25 = StaticKnowledgeRetriever((chunks[1], chunks[0]))
    semantic = StaticKnowledgeRetriever((chunks[0], chunks[2]))
    retriever: KnowledgeRetriever = HybridKnowledgeRetriever(
        chunks,
        bm25_retriever=bm25,
        semantic_retriever=semantic,
    )

    results = retriever.search("station readiness", limit=2)

    assert [result.chunk_id for result in results] == [
        "a::chunk-001",
        "b::chunk-001",
    ]
    assert results[0].document_id == chunks[0].document_id
    assert results[0].source == chunks[0].source
    assert results[0].content == chunks[0].content
    assert results[0].metadata == chunks[0].metadata
    assert results[0].relevance_score is not None
    assert bm25.requests == [("station readiness", 3)]
    assert semantic.requests == [("station readiness", 3)]


def test_hybrid_retriever_is_deterministic_with_different_component_ordering() -> None:
    chunks = (chunk("a::chunk-001"), chunk("b::chunk-001"))
    retriever = HybridKnowledgeRetriever(
        chunks,
        bm25_retriever=StaticKnowledgeRetriever((chunks[1], chunks[0])),
        semantic_retriever=StaticKnowledgeRetriever((chunks[0], chunks[1])),
    )

    assert retriever.search("query", limit=2) == retriever.search("query", limit=2)


def test_hybrid_retriever_rejects_empty_query_and_invalid_limit() -> None:
    source_chunk = chunk("a::chunk-001")
    retriever = HybridKnowledgeRetriever(
        (source_chunk,),
        bm25_retriever=StaticKnowledgeRetriever((source_chunk,)),
        semantic_retriever=StaticKnowledgeRetriever((source_chunk,)),
    )

    with pytest.raises(ValueError, match="query must not be empty"):
        retriever.search("   ", limit=1)
    with pytest.raises(ValueError, match="limit must be at least 1"):
        retriever.search("query", limit=0)


def test_hybrid_retriever_rejects_component_result_without_known_provenance() -> None:
    source_chunk = chunk("a::chunk-001")
    retriever = HybridKnowledgeRetriever(
        (source_chunk,),
        bm25_retriever=StaticKnowledgeRetriever((chunk("unknown::chunk-001"),)),
        semantic_retriever=StaticKnowledgeRetriever(()),
    )

    with pytest.raises(ValueError, match="unknown chunk_id"):
        retriever.search("query", limit=1)
