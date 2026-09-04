from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)


class LangChainChatModel(Protocol):
    @property
    def model_profile(self) -> ModelProfile: ...

    def bind_tools(self, tools: Sequence[BaseTool]) -> LangChainChatModel: ...

    def invoke(self, messages: Sequence[BaseMessage]) -> AIMessage: ...


def to_llm_response(message: AIMessage) -> LLMResponse:
    tool_calls = tuple(
        LLMToolCall(
            id=_require_tool_call_id(tool_call.get("id")),
            name=tool_call["name"],
            arguments=dict(tool_call["args"]),
        )
        for tool_call in message.tool_calls
    )
    text_present = message.response_metadata.get("internal_text_present", True)
    if not isinstance(message.content, str):
        raise TypeError("Only text LangChain message content is supported")
    return LLMResponse(
        text=message.content if text_present else None,
        tool_calls=tool_calls,
        finish_reason=(FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP),
    )


def _require_tool_call_id(tool_call_id: object | None) -> str:
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ValueError("Tool call requires a non-empty ID")
    return tool_call_id
