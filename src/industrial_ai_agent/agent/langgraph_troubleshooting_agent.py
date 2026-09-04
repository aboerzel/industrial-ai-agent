from __future__ import annotations

from typing import Annotated, Literal, cast

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError
from typing_extensions import TypedDict

from industrial_ai_agent.agent.langchain_model import (
    LangChainChatModel,
    to_llm_response,
)
from industrial_ai_agent.agent.llm import LLMResponse
from industrial_ai_agent.agent.troubleshooting_agent import (
    GET_MACHINE_STATUS_TOOL,
    GET_PRODUCT_HISTORY_TOOL,
    MAX_TOOL_CALLS,
    TROUBLESHOOTING_SYSTEM_MESSAGE,
    AgentRunResult,
    AgentRunStatus,
    ExecutedToolCall,
    InvalidToolArgumentsError,
    MachineStatusToolArguments,
    MissingLLMResponseTextError,
    ProductHistoryToolArguments,
    ToolCallLimitExceededError,
    UnknownToolError,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability


class TroubleshootingGraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    executed_tool_count: int
    executed_tool_calls: tuple[ExecutedToolCall, ...]
    run_status: AgentRunStatus | None
    final_answer: str | None


class LangGraphTroubleshootingAgent:
    def __init__(
        self,
        chat_model: LangChainChatModel,
        product_history: ProductHistoryCapability,
        machine_status: MachineStatusCapability,
    ) -> None:
        self._product_history = product_history
        self._machine_status = machine_status
        self._tools = self._create_tools()
        self._tools_by_name = {tool.name: tool for tool in self._tools}
        self._chat_model = chat_model.bind_tools(self._tools)
        self._graph = self._build_graph()

    def request_tool_selection(self, user_request: str) -> LLMResponse:
        response = self._chat_model.invoke(self._initial_messages(user_request))
        return to_llm_response(response)

    def invoke(self, user_request: str) -> TroubleshootingGraphState:
        config: RunnableConfig = {"recursion_limit": 12}
        state = self._graph.invoke(
            {
                "messages": self._initial_messages(user_request),
                "executed_tool_count": 0,
                "executed_tool_calls": (),
                "run_status": None,
                "final_answer": None,
            },
            config=config,
        )
        return cast(TroubleshootingGraphState, state)

    def answer(self, user_request: str) -> AgentRunResult:
        state = self.invoke(user_request)
        run_status = state["run_status"]
        if run_status is None:
            raise RuntimeError("LangGraph run terminated without a status")
        return AgentRunResult(
            status=run_status,
            final_answer=state["final_answer"],
            tool_call_count=state["executed_tool_count"],
            executed_tool_calls=state["executed_tool_calls"],
        )

    def _build_graph(self):
        # noinspection PyTypeChecker
        builder = StateGraph(TroubleshootingGraphState)
        # noinspection PyTypeChecker
        builder.add_node("model", self._model_node)
        # noinspection PyTypeChecker
        builder.add_node("tool", self._tool_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", self._route_after_model)
        builder.add_edge("tool", "model")
        return builder.compile()

    def _model_node(self, state: TroubleshootingGraphState) -> dict[str, object]:
        message = self._chat_model.invoke(state["messages"])
        response = to_llm_response(message)
        if len(response.tool_calls) > 1:
            raise ToolCallLimitExceededError(
                "At most one tool call per LLM response is allowed"
            )
        if not response.tool_calls:
            if response.text is None:
                raise MissingLLMResponseTextError("LLM response did not contain text")
            return {
                "messages": [message],
                "run_status": AgentRunStatus.SUCCESS,
                "final_answer": response.text,
            }
        if state["executed_tool_count"] == MAX_TOOL_CALLS:
            return {
                "messages": [message],
                "run_status": AgentRunStatus.LIMIT_REACHED,
                "final_answer": None,
            }
        return {"messages": [message]}

    @staticmethod
    def _route_after_model(
        state: TroubleshootingGraphState,
    ) -> Literal["tool", "__end__"]:
        return END if state["run_status"] is not None else "tool"

    def _tool_node(self, state: TroubleshootingGraphState) -> dict[str, object]:
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or len(message.tool_calls) != 1:
            raise RuntimeError("Tool node requires exactly one AI tool call")

        tool_call = message.tool_calls[0]
        tool_name = tool_call["name"]
        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            raise UnknownToolError(f"Unknown tool: {tool_name}")

        arguments = self._validate_tool_arguments(tool_name, dict(tool_call["args"]))
        result = tool.invoke(arguments)
        executed_call = ExecutedToolCall(tool=tool_name, arguments=arguments)
        return {
            "messages": [
                ToolMessage(
                    content=str(result),
                    tool_call_id=_require_tool_call_id(tool_call.get("id")),
                )
            ],
            "executed_tool_count": state["executed_tool_count"] + 1,
            "executed_tool_calls": (*state["executed_tool_calls"], executed_call),
        }

    @staticmethod
    def _validate_tool_arguments(
        tool_name: str,
        raw_arguments: dict[str, object],
    ) -> dict[str, object]:
        try:
            if tool_name == GET_PRODUCT_HISTORY_TOOL.name:
                return ProductHistoryToolArguments.model_validate(
                    raw_arguments
                ).model_dump()
            if tool_name == GET_MACHINE_STATUS_TOOL.name:
                return MachineStatusToolArguments.model_validate(
                    raw_arguments
                ).model_dump()
        except ValidationError as error:
            raise InvalidToolArgumentsError(
                f"Invalid arguments for {tool_name}"
            ) from error
        raise UnknownToolError(f"Unknown tool: {tool_name}")

    def _create_tools(self) -> tuple[BaseTool, ...]:
        def get_product_history(product_id: str) -> str:
            result = self._product_history.get_product_history(product_id)
            return result.model_dump_json()

        def get_machine_status(station_id: str) -> str:
            result = self._machine_status.get_machine_status(station_id)
            return result.model_dump_json()

        return (
            StructuredTool.from_function(
                func=get_product_history,
                name=GET_PRODUCT_HISTORY_TOOL.name,
                description=GET_PRODUCT_HISTORY_TOOL.description,
                args_schema=ProductHistoryToolArguments,
            ),
            StructuredTool.from_function(
                func=get_machine_status,
                name=GET_MACHINE_STATUS_TOOL.name,
                description=GET_MACHINE_STATUS_TOOL.description,
                args_schema=MachineStatusToolArguments,
            ),
        )

    @staticmethod
    def _initial_messages(user_request: str) -> list[AnyMessage]:
        normalized_request = user_request.strip()
        if not normalized_request:
            raise ValueError("User request must not be empty")
        system_content = TROUBLESHOOTING_SYSTEM_MESSAGE.content
        if system_content is None:
            raise RuntimeError("Troubleshooting system message must contain text")
        return [
            SystemMessage(content=system_content),
            HumanMessage(content=normalized_request),
        ]


def _require_tool_call_id(tool_call_id: object | None) -> str:
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ValueError("Tool call requires a non-empty ID")
    return tool_call_id
