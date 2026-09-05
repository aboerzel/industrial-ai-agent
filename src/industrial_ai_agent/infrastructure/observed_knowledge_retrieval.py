"""Safe OpenTelemetry decorators for stable local retrieval boundaries."""

from collections.abc import Sequence

from industrial_ai_agent.domain.embedding_client import EmbeddingClient, EmbeddingVector
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.domain.reranker import Reranker
from industrial_ai_agent.infrastructure.telemetry import Telemetry


class ObservedEmbeddingClient:
    """Wrap embedding calls without recording query text or vectors."""

    def __init__(
        self,
        delegate: EmbeddingClient,
        *,
        telemetry: Telemetry | None,
        model: str,
    ) -> None:
        self._delegate = delegate
        self._telemetry = telemetry
        self._model = model

    def embed_query(self, text: str) -> EmbeddingVector:
        return self._observe(lambda: self._delegate.embed_query(text))

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        return self._observe(lambda: self._delegate.embed_documents(texts))

    def _observe(self, operation):
        if self._telemetry is None:
            return operation()
        with self._telemetry.span(
            "retrieval.embedding", {"embedding.model": self._model}
        ):
            return operation()


class ObservedKnowledgeRetriever:
    """Wrap one retrieval stage while retaining the inner port contract."""

    def __init__(
        self,
        delegate: KnowledgeRetriever,
        *,
        telemetry: Telemetry | None,
        span_name: str,
        strategy: str,
    ) -> None:
        self._delegate = delegate
        self._telemetry = telemetry
        self._span_name = span_name
        self._strategy = strategy

    def search(self, query: str, limit: int) -> tuple[KnowledgeRetrievalResult, ...]:
        if self._telemetry is None:
            return self._delegate.search(query, limit)
        with self._telemetry.span(
            self._span_name, {"retrieval.strategy": self._strategy}
        ) as span:
            results = self._delegate.search(query, limit)
            self._telemetry.set_span_attributes(
                span,
                {
                    "retrieval.candidate_count": limit,
                    "retrieval.result_count": len(results),
                },
            )
            return results


class ObservedReranker:
    """Wrap reranking without emitting candidates, scores, or document content."""

    def __init__(
        self,
        delegate: Reranker,
        *,
        telemetry: Telemetry | None,
        model: str,
    ) -> None:
        self._delegate = delegate
        self._telemetry = telemetry
        self._model = model

    def rerank(
        self,
        query: str,
        candidates: Sequence[KnowledgeRetrievalResult],
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        if self._telemetry is None:
            return self._delegate.rerank(query, candidates)
        with self._telemetry.span(
            "retrieval.rerank",
            {
                "reranker.model": self._model,
                "retrieval.candidate_count": len(candidates),
            },
        ) as span:
            results = self._delegate.rerank(query, candidates)
            self._telemetry.set_span_attributes(
                span, {"retrieval.result_count": len(results)}
            )
            return results
