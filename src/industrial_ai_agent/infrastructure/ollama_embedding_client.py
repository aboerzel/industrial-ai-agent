from collections.abc import Sequence

from langchain_ollama import OllamaEmbeddings

from industrial_ai_agent.application.embedding_egress import (
    EmbeddingExecutionAuthorizer,
)
from industrial_ai_agent.domain.embedding_client import EmbeddingVector
from industrial_ai_agent.domain.security import DataClassification

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
        self._model = model
        self._base_url = base_url
        self._authorizer = EmbeddingExecutionAuthorizer()
        self._embeddings: OllamaEmbeddings | None = None

    def embed_query(
        self, text: str, *, classification: DataClassification | None = None
    ) -> EmbeddingVector:
        embeddings = self._authorized_provider(classification)
        return tuple(float(value) for value in embeddings.embed_query(text))

    def embed_documents(
        self, texts: Sequence[str], *, classification: DataClassification | None = None
    ) -> tuple[EmbeddingVector, ...]:
        embeddings = self._authorized_provider(classification)
        return tuple(
            tuple(float(value) for value in vector)
            for vector in embeddings.embed_documents(list(texts))
        )

    def _authorized_provider(
        self, classification: DataClassification | None
    ) -> OllamaEmbeddings:
        destination = self._authorizer.require_allowed(classification, self._base_url)
        if self._embeddings is None:
            self._embeddings = OllamaEmbeddings(
                model=self._model,
                base_url=destination,
                client_kwargs={"trust_env": False, "follow_redirects": False},
            )
        return self._embeddings
