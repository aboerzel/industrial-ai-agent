from collections.abc import Sequence
from typing import Protocol

from industrial_ai_agent.domain.security import DataClassification

type EmbeddingVector = tuple[float, ...]


class EmbeddingClient(Protocol):
    """Provider-independent text embedding capability for semantic retrieval."""

    def embed_query(
        self, text: str, *, classification: DataClassification | None = None
    ) -> EmbeddingVector: ...

    def embed_documents(
        self, texts: Sequence[str], *, classification: DataClassification | None = None
    ) -> tuple[EmbeddingVector, ...]: ...
