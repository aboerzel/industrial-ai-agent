from collections.abc import Sequence

import torch
from sentence_transformers import CrossEncoder

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


class SentenceTransformersCrossEncoderReranker:
    """Local Sentence Transformers cross-encoder adapter behind the Reranker port."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_RERANKER_MODEL,
        device: str | None = None,
        local_files_only: bool = True,
    ) -> None:
        self.device = device or _default_device()
        self._cross_encoder = CrossEncoder(
            model,
            device=self.device,
            local_files_only=local_files_only,
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[KnowledgeRetrievalResult],
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if not candidates:
            return ()

        scores = self._cross_encoder.predict(
            [(normalized_query, candidate.content) for candidate in candidates],
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        ranked_candidates = tuple(
            candidate.model_copy(update={"relevance_score": float(score)})
            for candidate, score in zip(candidates, scores, strict=True)
        )
        return tuple(
            sorted(
                ranked_candidates,
                key=lambda candidate: (
                    -(candidate.relevance_score or 0.0),
                    candidate.chunk_id,
                ),
            )
        )


def _default_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"
