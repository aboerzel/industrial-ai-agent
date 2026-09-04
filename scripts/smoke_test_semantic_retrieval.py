from pathlib import Path

from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    load_markdown_chunks,
)
from industrial_ai_agent.infrastructure.in_memory_semantic_knowledge_retriever import (
    InMemorySemanticKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.ollama_embedding_client import (
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    OllamaEmbeddingClient,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"
QUERY = "How do I verify that S02 is ready again after repair?"


def main() -> None:
    retriever = InMemorySemanticKnowledgeRetriever(
        load_markdown_chunks(KNOWLEDGE_BASE_PATH),
        OllamaEmbeddingClient(),
    )
    results = retriever.search(QUERY, limit=3)

    print(f"model={DEFAULT_OLLAMA_EMBEDDING_MODEL}")
    print(f"query={QUERY}")
    for position, result in enumerate(results, start=1):
        score = result.relevance_score
        if score is None:
            raise RuntimeError("Semantic smoke result did not contain a score")
        print(
            f"{position}. chunk_id={result.chunk_id} score={score:.6f} "
            f"source={result.source} title={result.metadata['title']}"
        )


if __name__ == "__main__":
    main()
