from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_TOOL_CALLS = 3


class UnknownToolError(ValueError):
    pass


class InvalidToolArgumentsError(ValueError):
    pass


class ToolCallLimitExceededError(RuntimeError):
    pass


class MissingLLMResponseTextError(RuntimeError):
    pass


class AgentRunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    LIMIT_REACHED = "LIMIT_REACHED"


class ExecutedToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    arguments: dict[str, Any]

    @field_validator("tool")
    @classmethod
    def validate_tool(cls, tool: str) -> str:
        normalized_tool = tool.strip()
        if not normalized_tool:
            raise ValueError("tool must not be empty")
        return normalized_tool


class AgentRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: AgentRunStatus
    final_answer: str | None = None
    tool_call_count: int = Field(ge=0, le=MAX_TOOL_CALLS)
    executed_tool_calls: tuple[ExecutedToolCall, ...] = ()
    model_profile_name: str | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        if self.tool_call_count != len(self.executed_tool_calls):
            raise ValueError(
                "tool_call_count must match the number of executed tool calls"
            )
        if self.status is AgentRunStatus.SUCCESS and self.final_answer is None:
            raise ValueError("SUCCESS requires a final answer")
        if self.status is AgentRunStatus.LIMIT_REACHED:
            if self.final_answer is not None:
                raise ValueError("LIMIT_REACHED cannot contain a final answer")
            if self.tool_call_count != MAX_TOOL_CALLS:
                raise ValueError(
                    f"LIMIT_REACHED requires {MAX_TOOL_CALLS} executed tool calls"
                )
        return self
