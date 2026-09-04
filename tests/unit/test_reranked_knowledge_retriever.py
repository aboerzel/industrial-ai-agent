from collections.abc import Sequence
from inspect import getsource

import pytest

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.domain.reranker import Reranker
from industrial_ai_agent.infrastructure.reranked_knowledge_retriever import (
    RerankedKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.sentence_transformers_reranker import (
    SentenceTransformersCrossEncoderReranker,
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


class FakeReranker:
    def __init__(self, results: Sequence[KnowledgeRetrievalResult]) -> None:
        self._results = tuple(results)
        self.requests: list[tuple[str, tuple[KnowledgeRetrievalResult, ...]]] = []

    def rerank(
        self,
        query: str,
        candidates: Sequence[KnowledgeRetrievalResult],
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        self.requests.append((query, tuple(candidates)))
        return self._results


def test_reranker_port_exposes_no_framework_types() -> None:
    source = getsource(Reranker)

    assert "sentence_transformers" not in source
    assert "transformers" not in source
    assert "torch" not in source


def test_reranked_retriever_passes_complete_candidate_set_and_reorders_it() -> None:
    candidates = (chunk("a::chunk-001"), chunk("b::chunk-001"), chunk("c::chunk-001"))
    reranker = FakeReranker(
        (
            candidates[2].model_copy(update={"relevance_score": 0.9}),
            candidates[0].model_copy(update={"relevance_score": 0.8}),
            candidates[1].model_copy(update={"relevance_score": 0.7}),
        )
    )
    candidate_retriever = StaticKnowledgeRetriever(candidates)
    retriever: KnowledgeRetriever = RerankedKnowledgeRetriever(
        candidate_retriever=candidate_retriever,
        reranker=reranker,
        candidate_limit=3,
    )

    results = retriever.search("station readiness", limit=2)

    assert candidate_retriever.requests == [("station readiness", 3)]
    assert [item.chunk_id for item in reranker.requests[0][1]] == [
        "a::chunk-001",
        "b::chunk-001",
        "c::chunk-001",
    ]
    assert [item.chunk_id for item in results] == ["c::chunk-001", "a::chunk-001"]
    assert results[0].document_id == candidates[2].document_id
    assert results[0].source == candidates[2].source
    assert results[0].metadata == candidates[2].metadata
    assert results[0].relevance_score == 0.9


@pytest.mark.parametrize(
    "reranked_results, message",
    [
        ((chunk("a::chunk-001"),), "exactly the supplied"),
        (
            (chunk("a::chunk-001"), chunk("foreign::chunk-001")),
            "exactly the supplied",
        ),
        (
            (chunk("a::chunk-001"), chunk("a::chunk-001")),
            "duplicate chunk_ids",
        ),
    ],
)
def test_reranked_retriever_rejects_missing_foreign_or_duplicate_candidates(
    reranked_results: Sequence[KnowledgeRetrievalResult],
    message: str,
) -> None:
    candidates = (chunk("a::chunk-001"), chunk("b::chunk-001"))
    retriever = RerankedKnowledgeRetriever(
        candidate_retriever=StaticKnowledgeRetriever(candidates),
        reranker=FakeReranker(reranked_results),
    )

    with pytest.raises(ValueError, match=message):
        retriever.search("query", limit=2)


def test_reranked_retriever_rejects_empty_query_and_invalid_limit() -> None:
    source_chunk = chunk("a::chunk-001")
    retriever = RerankedKnowledgeRetriever(
        candidate_retriever=StaticKnowledgeRetriever((source_chunk,)),
        reranker=FakeReranker((source_chunk,)),
    )

    with pytest.raises(ValueError, match="query must not be empty"):
        retriever.search("   ", limit=1)
    with pytest.raises(ValueError, match="limit must be at least 1"):
        retriever.search("query", limit=0)


def test_reranked_retriever_mapping_is_deterministic() -> None:
    candidates = (chunk("a::chunk-001"), chunk("b::chunk-001"))
    reranked = (
        candidates[1].model_copy(update={"relevance_score": 0.8}),
        candidates[0].model_copy(update={"relevance_score": 0.7}),
    )
    retriever = RerankedKnowledgeRetriever(
        candidate_retriever=StaticKnowledgeRetriever(candidates),
        reranker=FakeReranker(reranked),
    )

    assert retriever.search("query", limit=2) == retriever.search("query", limit=2)


def test_sentence_transformers_adapter_maps_scores_without_a_model_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCrossEncoder:
        def __init__(
            self,
            model: str,
            *,
            device: str,
            local_files_only: bool,
        ) -> None:
            assert model == "test-reranker"
            assert device == "cpu"
            assert local_files_only is True

        @staticmethod
        def predict(
            pairs: list[tuple[str, str]],
            *,
            convert_to_numpy: bool,
            show_progress_bar: bool,
        ) -> tuple[float, ...]:
            assert pairs == [
                ("station readiness", "Content for a::chunk-001"),
                ("station readiness", "Content for b::chunk-001"),
            ]
            assert convert_to_numpy is True
            assert show_progress_bar is False
            return 0.2, 0.8

    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.sentence_transformers_reranker.CrossEncoder",
        FakeCrossEncoder,
    )
    reranker = SentenceTransformersCrossEncoderReranker(
        model="test-reranker",
        device="cpu",
    )

    results = reranker.rerank(
        "station readiness",
        (chunk("a::chunk-001"), chunk("b::chunk-001")),
    )

    assert [result.chunk_id for result in results] == ["b::chunk-001", "a::chunk-001"]
    assert [result.relevance_score for result in results] == [0.8, 0.2]
