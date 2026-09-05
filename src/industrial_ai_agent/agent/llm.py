from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("Model profile name must not be empty")
        object.__setattr__(self, "name", normalized_name)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


class LLMToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any]


class LLMMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: MessageRole
    content: str | None
    tool_calls: tuple[LLMToolCall, ...] = ()
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def validate_role_fields(self) -> Self:
        if self.role is MessageRole.TOOL:
            if self.content is None or not self.tool_call_id or self.tool_calls:
                raise ValueError(
                    "Tool messages require content and tool_call_id and cannot "
                    "contain tool_calls"
                )
        elif self.role is MessageRole.ASSISTANT:
            if self.tool_call_id or (self.content is None and not self.tool_calls):
                raise ValueError(
                    "Assistant messages require content or tool_calls and cannot "
                    "contain tool_call_id"
                )
        elif self.content is None or self.tool_calls or self.tool_call_id:
            raise ValueError(
                "System and user messages require content and cannot contain "
                "tool-call fields"
            )
        return self


class LLMToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[LLMMessage, ...] = Field(min_length=1)
    tools: tuple[LLMToolDefinition, ...] = ()


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None
    tool_calls: tuple[LLMToolCall, ...] = ()
    finish_reason: FinishReason


class LLMClient(Protocol):
    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse: ...
