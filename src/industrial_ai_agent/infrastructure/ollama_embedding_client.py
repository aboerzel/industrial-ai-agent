from collections.abc import Sequence

from langchain_ollama import OllamaEmbeddings

from industrial_ai_agent.domain.embedding_client import EmbeddingVector

DEFAULT_OLLAMA_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
DEFAULT_OLLAMA_EMBEDDING_BASE_URL = "http://localhost:11434"


class OllamaEmbeddingClient:
    """Local Ollama adapter behind the provider-independent embedding port."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_OLLAMA_EMBEDDING_MODEL,
        base_url: str = DEFAULT_OLLAMA_EMBEDDING_BASE_URL,
    ) -> None:
        self._embeddings = OllamaEmbeddings(model=model, base_url=base_url)

    def embed_query(self, text: str) -> EmbeddingVector:
        return tuple(float(value) for value in self._embeddings.embed_query(text))

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        return tuple(
            tuple(float(value) for value in vector)
            for vector in self._embeddings.embed_documents(list(texts))
        )
