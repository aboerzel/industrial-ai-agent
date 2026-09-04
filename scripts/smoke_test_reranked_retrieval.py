from pathlib import Path

from industrial_ai_agent.infrastructure.hybrid_knowledge_retriever import (
    HybridKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryBm25KnowledgeRetriever,
    load_markdown_chunks,
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"
QUERY = "How do I verify that S02 is ready again after repair?"
FINAL_LIMIT = 3


def main() -> None:
    chunks = load_markdown_chunks(KNOWLEDGE_BASE_PATH)
    hybrid = HybridKnowledgeRetriever(
        chunks,
        bm25_retriever=InMemoryBm25KnowledgeRetriever(chunks),
        semantic_retriever=InMemorySemanticKnowledgeRetriever(
            chunks,
            OllamaEmbeddingClient(),
        ),
        candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
    )
    reranker = SentenceTransformersCrossEncoderReranker()
    reranked = RerankedKnowledgeRetriever(
        candidate_retriever=hybrid,
        reranker=reranker,
        candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
    )

    print(f"Device: {reranker.device}")
    print(f"Query: {QUERY}")
    print("Hybrid candidate ranking:")
    for position, result in enumerate(
        hybrid.search(QUERY, limit=DEFAULT_RERANK_CANDIDATE_LIMIT),
        start=1,
    ):
        print(
            f"{position}. {result.chunk_id} | score={_format_score(result.relevance_score)} "
            f"| source={result.source} | title={result.metadata['title']}"
        )

    print("Reranked Top 3:")
    for position, result in enumerate(
        reranked.search(QUERY, limit=FINAL_LIMIT), start=1
    ):
        print(
            f"{position}. {result.chunk_id} | score={_format_score(result.relevance_score)} "
            f"| source={result.source} | title={result.metadata['title']}"
        )


def _format_score(score: float | None) -> str:
    return f"{score:.6f}" if score is not None else "none"


if __name__ == "__main__":
    main()
