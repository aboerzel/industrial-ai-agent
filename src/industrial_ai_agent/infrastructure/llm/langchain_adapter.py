from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
    ModelProfile,
)


@dataclass(frozen=True, slots=True)
class LLMClientChatModel:
    llm_client: LLMClient
    model_profile: ModelProfile
    tools: tuple[BaseTool, ...] = ()

    def bind_tools(self, tools: Sequence[BaseTool]) -> LLMClientChatModel:
        return LLMClientChatModel(
            llm_client=self.llm_client,
            model_profile=self.model_profile,
            tools=tuple(tools),
        )

    def invoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        response = self.llm_client.chat(
            self.model_profile,
            LLMRequest(
                messages=tuple(_to_internal_message(message) for message in messages),
                tools=tuple(_to_internal_tool(tool) for tool in self.tools),
            ),
        )
        return _to_ai_message(response)


def _to_internal_message(message: BaseMessage) -> LLMMessage:
    if isinstance(message, SystemMessage):
        return LLMMessage(role=MessageRole.SYSTEM, content=_text_content(message))
    if isinstance(message, HumanMessage):
        return LLMMessage(role=MessageRole.USER, content=_text_content(message))
    if isinstance(message, ToolMessage):
        return LLMMessage(
            role=MessageRole.TOOL,
            content=_text_content(message),
            tool_call_id=message.tool_call_id,
        )
    if isinstance(message, AIMessage):
        tool_calls = tuple(
            LLMToolCall(
                id=_require_tool_call_id(tool_call.get("id")),
                name=tool_call["name"],
                arguments=dict(tool_call["args"]),
            )
            for tool_call in message.tool_calls
        )
        content = _text_content(message)
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            content=content if content or not tool_calls else None,
            tool_calls=tool_calls,
        )
    raise TypeError(f"Unsupported LangChain message type: {type(message).__name__}")


def _to_internal_tool(tool: BaseTool) -> LLMToolDefinition:
    schema_model = tool.get_input_schema()
    schema_factory = getattr(schema_model, "model_json_schema", None)
    if not callable(schema_factory):
        raise TypeError(f"Tool {tool.name} does not expose a Pydantic input schema")
    create_schema = cast(Callable[[], dict[str, Any]], schema_factory)
    schema = create_schema()
    schema.pop("title", None)
    return LLMToolDefinition(
        name=tool.name,
        description=tool.description,
        parameters=schema,
    )


def _to_ai_message(response: LLMResponse) -> AIMessage:
    return AIMessage(
        content=response.text or "",
        tool_calls=[
            {
                "name": tool_call.name,
                "args": tool_call.arguments,
                "id": tool_call.id,
                "type": "tool_call",
            }
            for tool_call in response.tool_calls
        ],
        response_metadata={
            "finish_reason": response.finish_reason.value,
            "internal_text_present": response.text is not None,
        },
    )


def _text_content(message: BaseMessage) -> str:
    if not isinstance(message.content, str):
        raise TypeError("Only text LangChain message content is supported")
    return message.content


def _require_tool_call_id(tool_call_id: object | None) -> str:
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ValueError("Tool call requires a non-empty ID")
    return tool_call_id
