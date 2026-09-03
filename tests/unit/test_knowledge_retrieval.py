from math import log
from pathlib import Path
from typing import Protocol

import pytest

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryIdfKnowledgeRetriever,
    InMemoryLexicalKnowledgeRetriever,
    load_markdown_chunks,
    smoothed_inverse_document_frequency,
)
from industrial_ai_agent.tools.documentation_search import (
    DEFAULT_DOCUMENTATION_RESULT_LIMIT,
    DocumentationSearchCapability,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"


def create_retriever() -> InMemoryLexicalKnowledgeRetriever:
    return InMemoryLexicalKnowledgeRetriever(load_markdown_chunks(KNOWLEDGE_BASE_PATH))


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
        "station_s04",
    }
    assert len(chunks) == 9


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
        "station_s04::chunk-001",
        "station_s04::chunk-002",
        "station_s04::chunk-003",
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


def test_exact_technical_identifier_is_ranked_first() -> None:
    results = create_retriever().search("E-STOP-17", limit=3)

    assert results[0].chunk_id == "error_codes::chunk-002"
    assert results[0].relevance_score == 1.0
    assert all("E-STOP-17" in result.content for result in results)


def test_ranking_is_deterministic() -> None:
    retriever = create_retriever()

    first_results = retriever.search("S04 emergency stop", limit=3)
    second_results = retriever.search("S04 emergency stop", limit=3)

    assert first_results == second_results


def test_top_k_limit_is_enforced() -> None:
    results = create_retriever().search("station S04 E-STOP-17", limit=2)

    assert len(results) == 2


def test_query_normalization_is_case_and_punctuation_insensitive() -> None:
    retriever = create_retriever()

    normalized = retriever.search("e-stop-17", limit=3)
    varied = retriever.search("  E-STOP-17!!!  ", limit=3)

    assert normalized == varied


def test_empty_or_tokenless_query_is_rejected() -> None:
    retriever = create_retriever()

    with pytest.raises(
        ValueError,
        match="query must contain at least one searchable token",
    ):
        retriever.search("...", limit=3)


def test_invalid_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="limit must be at least 1"):
        create_retriever().search("S04", limit=0)


def test_runtime_search_uses_prebuilt_chunks_without_rereading_documents(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "sample.md"
    document_path.write_text("# Original\n\nUniqueTerm", encoding="utf-8")
    retriever = InMemoryLexicalKnowledgeRetriever(load_markdown_chunks(tmp_path))
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


def test_idf_retriever_calculates_chunk_document_frequency() -> None:
    retriever = InMemoryIdfKnowledgeRetriever(
        (
            knowledge_chunk("a::chunk-001", "common rare"),
            knowledge_chunk("b::chunk-001", "common"),
            knowledge_chunk("c::chunk-001", "common"),
        )
    )

    assert retriever.document_frequency("common") == 3
    assert retriever.document_frequency("RARE!!!") == 1
    assert retriever.document_frequency("missing") == 0


def test_smoothed_idf_uses_explicit_formula() -> None:
    actual = smoothed_inverse_document_frequency(
        total_chunks=3,
        document_frequency=1,
    )

    assert actual == pytest.approx(log((3 + 1) / (1 + 1)) + 1)


def test_rare_terms_receive_more_weight_than_common_terms() -> None:
    retriever = InMemoryIdfKnowledgeRetriever(
        (
            knowledge_chunk("a::chunk-001", "common rare"),
            knowledge_chunk("b::chunk-001", "common"),
            knowledge_chunk("c::chunk-001", "common"),
        )
    )

    assert retriever.inverse_document_frequency(
        "rare"
    ) > retriever.inverse_document_frequency("common")
    assert retriever.search("common rare", limit=3)[0].chunk_id == "a::chunk-001"


def test_idf_ranking_is_deterministic_and_breaks_ties_by_chunk_id() -> None:
    retriever = InMemoryIdfKnowledgeRetriever(
        (
            knowledge_chunk("b::chunk-001", "shared"),
            knowledge_chunk("a::chunk-001", "shared"),
        )
    )

    first_results = retriever.search("shared", limit=2)
    second_results = retriever.search("shared", limit=2)

    assert first_results == second_results
    assert [result.chunk_id for result in first_results] == [
        "a::chunk-001",
        "b::chunk-001",
    ]


def test_idf_retriever_preserves_technical_identifiers() -> None:
    retriever = InMemoryIdfKnowledgeRetriever(
        (
            knowledge_chunk("error::chunk-001", "Error code E-STOP-17"),
            knowledge_chunk("station::chunk-001", "Station identifier S04"),
        )
    )

    error_results = retriever.search("e-stop-17", limit=1)
    station_results = retriever.search("s04", limit=1)

    assert error_results[0].chunk_id == "error::chunk-001"
    assert station_results[0].chunk_id == "station::chunk-001"


def test_idf_retriever_enforces_top_k_and_preserves_provenance() -> None:
    chunks = load_markdown_chunks(KNOWLEDGE_BASE_PATH)
    original_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    results = InMemoryIdfKnowledgeRetriever(chunks).search(
        "station S04 E-STOP-17",
        limit=2,
    )

    assert len(results) == 2
    for result in results:
        original = original_by_id[result.chunk_id]
        assert result.content == original.content
        assert result.document_id == original.document_id
        assert result.source == original.source
        assert result.metadata == original.metadata
        assert result.relevance_score is not None


@pytest.mark.parametrize(
    "retriever_factory",
    [InMemoryLexicalKnowledgeRetriever, InMemoryIdfKnowledgeRetriever],
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
    assert results[0].relevance_score == 1.0
