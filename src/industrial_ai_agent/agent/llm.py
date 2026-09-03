from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


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


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


class LLMMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str


class LLMToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]


class LLMToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: tuple[LLMMessage, ...] = Field(min_length=1)
    tools: tuple[LLMToolDefinition, ...] = ()


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str | None
    tool_calls: tuple[LLMToolCall, ...] = ()
    finish_reason: FinishReason


class LLMClient(Protocol):
    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse: ...
