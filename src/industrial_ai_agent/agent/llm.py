from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True, slots=True)
class ModelId:
    value: str

    def __post_init__(self) -> None:
        normalized_name = self.value.strip()
        if not normalized_name:
            raise ValueError("Model ID must not be empty")
        object.__setattr__(self, "value", normalized_name)

    @property
    def name(self) -> str:
        """Compatibility accessor for framework state migrated in a later schema step."""
        return self.value


# Transitional source compatibility for persisted LangGraph/run contracts. New model
# selection code uses ModelId and never treats this alias as a routing profile.
ModelProfile = ModelId


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
    REQUEST_INVALID = "llm_provider_request_invalid"


class LLMProviderError(RuntimeError):
    """A known provider failure without provider payload or response details."""

    def __init__(
        self,
        code: LLMProviderErrorCode,
        *,
        provider_error_type: str,
        provider_request_reason: str | None = None,
        provider_http_status: int | None = None,
        provider_error_category: str | None = None,
        provider_request_id: str | None = None,
        request_diagnostics: "LLMRequestDiagnostics | None" = None,
    ) -> None:
        super().__init__("LLM provider request failed")
        self.code = code.value
        self.error_stage = "llm_provider"
        self.provider_error_type = provider_error_type
        self.provider_request_reason = provider_request_reason
        self.provider_http_status = provider_http_status
        self.provider_error_category = provider_error_category
        self.provider_request_id = provider_request_id
        self.request_diagnostics = request_diagnostics


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


class LLMRequestDiagnostics(BaseModel):
    """Content-free structural metadata for correlating provider requests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_payload_bytes: int = Field(ge=0)
    message_count: int = Field(ge=1)
    tool_definition_count: int = Field(ge=0)
    has_tools: bool
    has_structured_output: bool
    structured_schema_hash: str | None = None


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
    request_diagnostics: LLMRequestDiagnostics | None = None
    reasoning_content_present: bool | None = None


class LLMClient(Protocol):
    def chat(self, model_id: ModelId, request: LLMRequest) -> LLMResponse: ...
