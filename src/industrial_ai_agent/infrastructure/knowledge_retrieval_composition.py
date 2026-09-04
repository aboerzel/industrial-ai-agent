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
from industrial_ai_agent.infrastructure.ollama_embedding_client import (
    OllamaEmbeddingClient,
)
from industrial_ai_agent.infrastructure.reranked_knowledge_retriever import (
    DEFAULT_RERANK_CANDIDATE_LIMIT,
    RerankedKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.sentence_transformers_reranker import (
    SentenceTransformersCrossEncoderReranker,
)


def create_reranked_knowledge_retriever(
    chunks: Sequence[KnowledgeRetrievalResult],
    *,
    embedding_base_url: str | None = None,
    reranker_device: str | None = None,
) -> KnowledgeRetriever:
    """Assemble the immutable BM25, semantic, RRF, and reranker baseline."""
    semantic_retriever = InMemorySemanticKnowledgeRetriever(
        chunks,
        OllamaEmbeddingClient(
            **({"base_url": embedding_base_url} if embedding_base_url else {})
        ),
    )
    hybrid_retriever = HybridKnowledgeRetriever(
        chunks,
        bm25_retriever=InMemoryBm25KnowledgeRetriever(chunks),
        semantic_retriever=semantic_retriever,
        candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
    )
    return RerankedKnowledgeRetriever(
        candidate_retriever=hybrid_retriever,
        reranker=SentenceTransformersCrossEncoderReranker(device=reranker_device),
        candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
    )
