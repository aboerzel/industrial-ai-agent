from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeRetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str
    document_id: str
    source: str
    chunk_id: str
    relevance_score: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "document_id", "source", "chunk_id")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Value must not be empty")
        return normalized_value
