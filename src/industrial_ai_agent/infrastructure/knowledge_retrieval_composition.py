"""Infrastructure composition for the frozen local reranked retrieval baseline."""

from collections.abc import Sequence

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.knowledge_retriever import KnowledgeRetriever
from industrial_ai_agent.infrastructure.hybrid_knowledge_retriever import (
    HybridKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryBm25KnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.in_memory_semantic_knowledge_retriever import (
    InMemorySemanticKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.observed_knowledge_retrieval import (
    ObservedEmbeddingClient,
    ObservedKnowledgeRetriever,
    ObservedReranker,
)
from industrial_ai_agent.infrastructure.ollama_embedding_client import (
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    OllamaEmbeddingClient,
)
from industrial_ai_agent.infrastructure.reranked_knowledge_retriever import (
    DEFAULT_RERANK_CANDIDATE_LIMIT,
    RerankedKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.sentence_transformers_reranker import (
    DEFAULT_RERANKER_MODEL,
    SentenceTransformersCrossEncoderReranker,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry


def create_reranked_knowledge_retriever(
    chunks: Sequence[KnowledgeRetrievalResult],
    *,
    embedding_base_url: str | None = None,
    reranker_device: str | None = None,
    reranker_local_files_only: bool = True,
    telemetry: Telemetry | None = None,
) -> KnowledgeRetriever:
    """Assemble the immutable BM25, semantic, RRF, and reranker baseline."""
    embedding_client = ObservedEmbeddingClient(
        OllamaEmbeddingClient(
            **({"base_url": embedding_base_url} if embedding_base_url else {})
        ),
        telemetry=telemetry,
        model=DEFAULT_OLLAMA_EMBEDDING_MODEL,
    )
    semantic_retriever = ObservedKnowledgeRetriever(
        InMemorySemanticKnowledgeRetriever(
            chunks,
            embedding_client,
        ),
        telemetry=telemetry,
        span_name="retrieval.semantic",
        strategy="semantic",
    )
    lexical_retriever = ObservedKnowledgeRetriever(
        InMemoryBm25KnowledgeRetriever(chunks),
        telemetry=telemetry,
        span_name="retrieval.lexical",
        strategy="bm25",
    )
    hybrid_retriever = ObservedKnowledgeRetriever(
        HybridKnowledgeRetriever(
            chunks,
            bm25_retriever=lexical_retriever,
            semantic_retriever=semantic_retriever,
            candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
        ),
        telemetry=telemetry,
        span_name="retrieval.fusion",
        strategy="reciprocal_rank_fusion",
    )
    return RerankedKnowledgeRetriever(
        candidate_retriever=hybrid_retriever,
        reranker=ObservedReranker(
            SentenceTransformersCrossEncoderReranker(
                device=reranker_device,
                local_files_only=reranker_local_files_only,
            ),
            telemetry=telemetry,
            model=DEFAULT_RERANKER_MODEL,
        ),
        candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
    )
