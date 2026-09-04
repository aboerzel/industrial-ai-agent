"""Public FastAPI request and response contracts."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = "ok"


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(
        description="Troubleshooting request for the industrial agent."
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, message: str) -> str:
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message must not be empty")
        return normalized_message


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    arguments: dict[str, Any]


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    status: RunStatus
    answer: str | None = None
    tool_calls: tuple[ToolCallResponse, ...] = ()


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
