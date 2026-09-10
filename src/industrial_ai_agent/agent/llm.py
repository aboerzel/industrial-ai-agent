from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, Self

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


class LLMProviderErrorCode(StrEnum):
    """Closed provider-failure categories safe to cross the LLM port."""

    RATE_LIMIT = "llm_rate_limit"
    QUOTA_EXCEEDED = "llm_quota_exceeded"
    PROVIDER_UNAVAILABLE = "llm_provider_unavailable"


class LLMProviderError(RuntimeError):
    """A known provider failure without provider payload or response details."""

    def __init__(
        self,
        code: LLMProviderErrorCode,
        *,
        provider_error_type: str,
    ) -> None:
        super().__init__("LLM provider request failed")
        self.code = code.value
        self.error_stage = "llm_provider"
        self.provider_error_type = provider_error_type


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


class LLMJsonSchema(BaseModel):
    """Provider-neutral JSON Schema envelope for a bounded structured response."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    schema_definition: dict[str, Any] = Field(
        validation_alias="schema",
        serialization_alias="schema",
    )
    strict: Literal[True] = True


class LLMResponseFormat(BaseModel):
    """A structured response request supported only by configured adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["json_schema"] = "json_schema"
    json_schema: LLMJsonSchema


class LLMReasoningEffort(StrEnum):
    """Semantic reasoning budget understood by supporting provider adapters."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[LLMMessage, ...] = Field(min_length=1)
    tools: tuple[LLMToolDefinition, ...] = ()
    response_format: LLMResponseFormat | None = None
    reasoning_effort: LLMReasoningEffort | None = None


class LLMUsage(BaseModel):
    """Provider-reported token usage; omitted when the provider does not supply it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None
    tool_calls: tuple[LLMToolCall, ...] = ()
    finish_reason: FinishReason
    usage: LLMUsage | None = None


class LLMClient(Protocol):
    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse: ...
