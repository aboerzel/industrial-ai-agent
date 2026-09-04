from collections.abc import Sequence
from inspect import getsource

import pytest

from industrial_ai_agent.domain.embedding_client import EmbeddingClient, EmbeddingVector
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.infrastructure.in_memory_semantic_knowledge_retriever import (
    InMemorySemanticKnowledgeRetriever,
)


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.document_requests: list[tuple[str, ...]] = []
        self.query_requests: list[str] = []

    def embed_query(self, text: str) -> EmbeddingVector:
        self.query_requests.append(text)
        return self._embed(text)

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        self.document_requests.append(tuple(texts))
        return tuple(self._embed(text) for text in texts)

    @staticmethod
    def _embed(text: str) -> EmbeddingVector:
        normalized = text.casefold()
        if "repair" in normalized or "ready" in normalized or "homing" in normalized:
            return 1.0, 0.0, 0.0
        if "calibration" in normalized or "camera" in normalized:
            return 0.0, 1.0, 0.0
        if "quality" in normalized or "inspection" in normalized:
            return 0.0, 0.0, 1.0
        return 0.5, 0.5, 0.5


def chunk(chunk_id: str, content: str) -> KnowledgeRetrievalResult:
    document_id = chunk_id.split("::", maxsplit=1)[0]
    return KnowledgeRetrievalResult(
        content=content,
        document_id=document_id,
        source=f"{document_id}.md",
        chunk_id=chunk_id,
        metadata={"title": chunk_id},
    )


def test_embedding_port_supports_single_query_and_batch_documents() -> None:
    client: EmbeddingClient = FakeEmbeddingClient()

    assert client.embed_query("repair") == (1.0, 0.0, 0.0)
    assert client.embed_documents(("repair", "camera")) == (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    )


def test_embedding_port_exposes_no_langchain_or_provider_types() -> None:
    source = getsource(EmbeddingClient)

    assert "langchain" not in source.casefold()
    assert "ollama" not in source.casefold()


def test_semantic_retriever_builds_document_index_once() -> None:
    embeddings = FakeEmbeddingClient()
    retriever = InMemorySemanticKnowledgeRetriever(
        (
            chunk("station::chunk-001", "Confirm homing after repair."),
            chunk("vision::chunk-001", "Camera calibration procedure."),
        ),
        embeddings,
    )

    assert embeddings.document_requests == [
        ("Confirm homing after repair.", "Camera calibration procedure.")
    ]

    retriever.search("Is the station ready after repair?", limit=1)

    assert len(embeddings.document_requests) == 1
    assert embeddings.query_requests == ["Is the station ready after repair?"]


def test_semantic_retriever_preserves_provenance_and_stable_chunk_mapping() -> None:
    source_chunk = chunk("station::chunk-001", "Confirm homing after repair.")
    retriever = InMemorySemanticKnowledgeRetriever(
        (source_chunk, chunk("vision::chunk-001", "Camera calibration procedure.")),
        FakeEmbeddingClient(),
    )

    result = retriever.search("Verify ready after repair", limit=1)[0]

    assert result.chunk_id == source_chunk.chunk_id
    assert result.document_id == source_chunk.document_id
    assert result.source == source_chunk.source
    assert result.content == source_chunk.content
    assert result.metadata == source_chunk.metadata
    assert result.relevance_score is not None


def test_semantic_retriever_enforces_top_k_and_is_deterministic() -> None:
    retriever = InMemorySemanticKnowledgeRetriever(
        (
            chunk("b::chunk-001", "Confirm homing after repair."),
            chunk("a::chunk-001", "Confirm homing after repair."),
            chunk("vision::chunk-001", "Camera calibration procedure."),
        ),
        FakeEmbeddingClient(),
    )

    first_results = retriever.search("ready after repair", limit=2)
    second_results = retriever.search("ready after repair", limit=2)

    assert [result.chunk_id for result in first_results] == [
        "a::chunk-001",
        "b::chunk-001",
    ]
    assert first_results == second_results


def test_semantic_retriever_rejects_empty_query_and_invalid_limit() -> None:
    retriever = InMemorySemanticKnowledgeRetriever(
        (chunk("station::chunk-001", "Confirm homing after repair."),),
        FakeEmbeddingClient(),
    )

    with pytest.raises(ValueError, match="query must not be empty"):
        retriever.search("   ", limit=1)
    with pytest.raises(ValueError, match="limit must be at least 1"):
        retriever.search("repair", limit=0)


def test_semantic_retriever_fulfills_knowledge_retriever_port() -> None:
    retriever: KnowledgeRetriever = InMemorySemanticKnowledgeRetriever(
        (chunk("station::chunk-001", "Confirm homing after repair."),),
        FakeEmbeddingClient(),
    )

    results = retriever.search("ready after repair", limit=1)

    assert results[0].chunk_id == "station::chunk-001"
