from collections.abc import Iterable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from industrial_ai_agent.agent.model_egress import ModelEgressDeniedError
from industrial_ai_agent.domain.embedding_client import EmbeddingClient
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.security import (
    DataClassification,
    effective_data_classification,
)


class InMemorySemanticKnowledgeRetriever:
    """Semantic KnowledgeRetriever backed by LangChain's in-memory vector store."""

    def __init__(
        self,
        chunks: Iterable[KnowledgeRetrievalResult],
        embedding_client: EmbeddingClient,
        *,
        query_classification: DataClassification | None = None,
    ) -> None:
        indexed_chunks = tuple(chunks)
        self._chunks_by_id = {chunk.chunk_id: chunk for chunk in indexed_chunks}
        if not self._chunks_by_id:
            raise ValueError("Semantic index must contain at least one chunk")
        if len(self._chunks_by_id) != len(indexed_chunks):
            raise ValueError("Semantic index must not contain duplicate chunk_ids")
        if any(
            "classification" not in chunk.model_fields_set
            or not isinstance(chunk.classification, DataClassification)
            for chunk in indexed_chunks
        ):
            raise ModelEgressDeniedError("Model egress denied by policy")

        self._vector_store = InMemoryVectorStore(
            embedding=_LangChainEmbeddingAdapter(
                embedding_client,
                document_classification=effective_data_classification(
                    *(chunk.classification for chunk in indexed_chunks)
                ),
                query_classification=query_classification,
            )
        )
        self._vector_store.add_documents(
            [
                Document(
                    page_content=chunk.content,
                    metadata={"chunk_id": chunk.chunk_id},
                )
                for chunk in self._chunks_by_id.values()
            ]
        )

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        scored_documents = self._vector_store.similarity_search_with_score(
            normalized_query,
            k=limit,
        )
        ranked_results = sorted(
            scored_documents,
            key=lambda item: (-item[1], _chunk_id_from_document(item[0])),
        )
        return tuple(
            self._chunks_by_id[_chunk_id_from_document(document)].model_copy(
                update={"relevance_score": score}
            )
            for document, score in ranked_results
        )


class _LangChainEmbeddingAdapter(Embeddings):
    """Infrastructure-only translation from the inner port to LangChain's contract."""

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        *,
        document_classification: DataClassification,
        query_classification: DataClassification | None,
    ) -> None:
        self._embedding_client = embedding_client
        self._document_classification = document_classification
        self._query_classification = query_classification

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            list(vector)
            for vector in self._embedding_client.embed_documents(
                texts, classification=self._document_classification
            )
        ]

    def embed_query(self, text: str) -> list[float]:
        if not isinstance(self._query_classification, DataClassification):
            raise ModelEgressDeniedError("Model egress denied by policy")
        return list(
            self._embedding_client.embed_query(
                text, classification=self._query_classification
            )
        )


def _chunk_id_from_document(document: Document) -> str:
    chunk_id = document.metadata.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise ValueError("Semantic vector document is missing chunk_id provenance")
    return chunk_id
