from collections.abc import Sequence
from typing import Protocol

type EmbeddingVector = tuple[float, ...]


class EmbeddingClient(Protocol):
    """Provider-independent text embedding capability for semantic retrieval."""

    def embed_query(self, text: str) -> EmbeddingVector: ...

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]: ...
