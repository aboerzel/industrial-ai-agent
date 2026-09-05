from math import log
from pathlib import Path
from typing import Protocol

import pytest

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_K1,
    InMemoryBm25KnowledgeRetriever,
    bm25_inverse_document_frequency,
    bm25_term_frequency_weight,
    load_markdown_chunks,
)
from industrial_ai_agent.tools.documentation_search import (
    DEFAULT_DOCUMENTATION_RESULT_LIMIT,
    DocumentationSearchCapability,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"


class RetrieverFactory(Protocol):
    def __call__(
        self,
        chunks: tuple[KnowledgeRetrievalResult, ...],
    ) -> KnowledgeRetriever: ...


def knowledge_chunk(chunk_id: str, content: str) -> KnowledgeRetrievalResult:
    document_id = chunk_id.split("::", maxsplit=1)[0]
    return KnowledgeRetrievalResult(
        content=content,
        document_id=document_id,
        source=f"{document_id}.md",
        chunk_id=chunk_id,
        metadata={"title": chunk_id},
    )


class RecordingKnowledgeRetriever:
    def __init__(self, *results: KnowledgeRetrievalResult) -> None:
        self._results = results
        self.requests: list[tuple[str, int]] = []

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        self.requests.append((query, limit))
        return self._results[:limit]


def test_loads_all_versioned_markdown_documents() -> None:
    chunks = load_markdown_chunks(KNOWLEDGE_BASE_PATH)

    assert {chunk.document_id for chunk in chunks} == {
        "error_codes",
        "maintenance",
        "production_quality",
        "station_s02",
        "station_s04",
        "troubleshooting_service",
        "vision_calibration",
    }
    assert len(chunks) == 25


def test_markdown_sections_receive_stable_ordered_chunk_ids() -> None:
    first_load = load_markdown_chunks(KNOWLEDGE_BASE_PATH)
    second_load = load_markdown_chunks(KNOWLEDGE_BASE_PATH)

    assert [chunk.chunk_id for chunk in first_load] == [
        "error_codes::chunk-001",
        "error_codes::chunk-002",
        "error_codes::chunk-003",
        "maintenance::chunk-001",
        "maintenance::chunk-002",
        "maintenance::chunk-003",
        "production_quality::chunk-001",
        "production_quality::chunk-002",
        "production_quality::chunk-003",
        "production_quality::chunk-004",
        "station_s02::chunk-001",
        "station_s02::chunk-002",
        "station_s02::chunk-003",
        "station_s02::chunk-004",
        "station_s04::chunk-001",
        "station_s04::chunk-002",
        "station_s04::chunk-003",
        "troubleshooting_service::chunk-001",
        "troubleshooting_service::chunk-002",
        "troubleshooting_service::chunk-003",
        "troubleshooting_service::chunk-004",
        "vision_calibration::chunk-001",
        "vision_calibration::chunk-002",
        "vision_calibration::chunk-003",
        "vision_calibration::chunk-004",
    ]
    assert first_load == second_load


def test_loaded_chunk_preserves_content_and_provenance() -> None:
    chunks = load_markdown_chunks(KNOWLEDGE_BASE_PATH)
    chunk = next(item for item in chunks if item.chunk_id == "station_s04::chunk-002")

    assert "P4711" in chunk.content
    assert "E-STOP-17" in chunk.content
    assert chunk.document_id == "station_s04"
    assert chunk.source == "station_s04.md"
    assert chunk.metadata == {
        "title": "Fault state and E-STOP-17",
        "format": "markdown",
    }
    assert chunk.relevance_score is None


def test_runtime_search_uses_prebuilt_chunks_without_rereading_documents(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "sample.md"
    document_path.write_text("# Original\n\nUniqueTerm", encoding="utf-8")
    retriever = InMemoryBm25KnowledgeRetriever(load_markdown_chunks(tmp_path))
    document_path.write_text("# Changed\n\nReplacement", encoding="utf-8")

    results = retriever.search("UniqueTerm", limit=1)

    assert results[0].chunk_id == "sample::chunk-001"
    assert "UniqueTerm" in results[0].content


def test_capability_uses_inner_port_and_returns_structured_results() -> None:
    expected_result = KnowledgeRetrievalResult(
        content="## E-STOP-17\nTechnical content.",
        document_id="error_codes",
        source="error_codes.md",
        chunk_id="error_codes::chunk-002",
        relevance_score=1.0,
        metadata={"title": "E-STOP-17"},
    )
    retriever = RecordingKnowledgeRetriever(expected_result)
    capability = DocumentationSearchCapability(retriever)

    result = capability.search_documentation("  E-STOP-17  ")

    assert result.query == "E-STOP-17"
    assert result.results == (expected_result,)
    assert retriever.requests == [("E-STOP-17", DEFAULT_DOCUMENTATION_RESULT_LIMIT)]


def test_capability_rejects_empty_query_without_calling_port() -> None:
    retriever = RecordingKnowledgeRetriever()
    capability = DocumentationSearchCapability(retriever)

    with pytest.raises(ValueError, match="query must not be empty"):
        capability.search_documentation("   ")

    assert retriever.requests == []


def test_capability_forwards_requested_top_k_to_the_inner_port() -> None:
    retriever = RecordingKnowledgeRetriever(
        knowledge_chunk("one::chunk-001", "one"),
        knowledge_chunk("two::chunk-001", "two"),
    )
    capability = DocumentationSearchCapability(retriever)

    result = capability.search_documentation("known query", top_k=1)

    assert len(result.results) == 1
    assert retriever.requests == [("known query", 1)]


def test_capability_rejects_invalid_top_k_without_calling_port() -> None:
    retriever = RecordingKnowledgeRetriever()
    capability = DocumentationSearchCapability(retriever)

    with pytest.raises(ValueError, match="top_k must be at least 1"):
        capability.search_documentation("known query", top_k=0)

    assert retriever.requests == []


def test_bm25_retriever_counts_term_and_document_frequency() -> None:
    retriever = InMemoryBm25KnowledgeRetriever(
        (
            knowledge_chunk("a::chunk-001", "target target common"),
            knowledge_chunk("b::chunk-001", "target common common"),
            knowledge_chunk("c::chunk-001", "common only"),
        )
    )

    assert retriever.term_frequency("a::chunk-001", "TARGET!!!") == 2
    assert retriever.term_frequency("b::chunk-001", "target") == 1
    assert retriever.document_frequency("target") == 2
    assert retriever.document_frequency("missing") == 0


def test_bm25_idf_uses_robertson_sparck_jones_formula() -> None:
    actual = bm25_inverse_document_frequency(
        total_chunks=3,
        document_frequency=1,
    )

    assert actual == pytest.approx(log(1 + (3 - 1 + 0.5) / (1 + 0.5)))


def test_bm25_calculates_average_chunk_length() -> None:
    retriever = InMemoryBm25KnowledgeRetriever(
        (
            knowledge_chunk("a::chunk-001", "one two"),
            knowledge_chunk("b::chunk-001", "one two three four"),
        )
    )

    assert retriever.average_chunk_length == 3.0


def test_bm25_term_frequency_saturates() -> None:
    weights = tuple(
        bm25_term_frequency_weight(
            term_frequency=term_frequency,
            chunk_length=10,
            average_chunk_length=10,
        )
        for term_frequency in (1, 2, 3)
    )

    assert weights[0] < weights[1] < weights[2]
    assert weights[1] - weights[0] > weights[2] - weights[1]


def test_bm25_length_normalization_favors_shorter_equal_tf_chunk() -> None:
    short_weight = bm25_term_frequency_weight(
        term_frequency=2,
        chunk_length=4,
        average_chunk_length=8,
    )
    long_weight = bm25_term_frequency_weight(
        term_frequency=2,
        chunk_length=12,
        average_chunk_length=8,
    )

    assert short_weight > long_weight
    assert DEFAULT_BM25_K1 == 1.5
    assert DEFAULT_BM25_B == 0.75


def test_bm25_term_frequency_affects_ranking_at_equal_length() -> None:
    retriever = InMemoryBm25KnowledgeRetriever(
        (
            knowledge_chunk("once::chunk-001", "target filler filler"),
            knowledge_chunk("twice::chunk-001", "target target filler"),
        )
    )

    results = retriever.search("target", limit=2)

    assert [result.chunk_id for result in results] == [
        "twice::chunk-001",
        "once::chunk-001",
    ]


def test_bm25_ranking_is_deterministic_and_breaks_ties_by_chunk_id() -> None:
    retriever = InMemoryBm25KnowledgeRetriever(
        (
            knowledge_chunk("b::chunk-001", "shared term"),
            knowledge_chunk("a::chunk-001", "shared term"),
        )
    )

    first_results = retriever.search("shared", limit=2)
    second_results = retriever.search("shared", limit=2)

    assert first_results == second_results
    assert [result.chunk_id for result in first_results] == [
        "a::chunk-001",
        "b::chunk-001",
    ]


def test_bm25_preserves_identifiers_top_k_and_provenance() -> None:
    chunks = load_markdown_chunks(KNOWLEDGE_BASE_PATH)
    original_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    results = InMemoryBm25KnowledgeRetriever(chunks).search("E-STOP-17 S04", limit=2)

    assert len(results) == 2
    assert results[0].chunk_id == "station_s04::chunk-002"
    for result in results:
        original = original_by_id[result.chunk_id]
        assert result.content == original.content
        assert result.document_id == original.document_id
        assert result.source == original.source
        assert result.metadata == original.metadata
        assert result.relevance_score is not None
        assert result.relevance_score > 0


@pytest.mark.parametrize(
    "retriever_factory",
    [
        InMemoryBm25KnowledgeRetriever,
    ],
)
def test_retrieval_implementations_fulfill_same_port_contract(
    retriever_factory: RetrieverFactory,
) -> None:
    chunks = (
        knowledge_chunk("a::chunk-001", "E-STOP-17 safety circuit"),
        knowledge_chunk("b::chunk-001", "quality inspection"),
    )
    retriever: KnowledgeRetriever = retriever_factory(chunks)

    results = retriever.search("E-STOP-17", limit=1)

    assert len(results) == 1
    assert results[0].chunk_id == "a::chunk-001"
    assert results[0].relevance_score is not None
    assert results[0].relevance_score > 0
