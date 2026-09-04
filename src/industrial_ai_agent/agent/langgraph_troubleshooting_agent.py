from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from enum import StrEnum
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
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import ValidationError
from typing_extensions import TypedDict

from industrial_ai_agent.agent.langchain_model import (
    LangChainChatModel,
    to_llm_response,
)
from industrial_ai_agent.agent.llm import LLMResponse
from industrial_ai_agent.agent.mcp_tool_provider import McpToolProvider, McpToolSession
from industrial_ai_agent.agent.model_egress import DataClassification
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
from industrial_ai_agent.tools.maintenance_ticket import (
    CreateMaintenanceTicketArguments,
    MaintenanceTicketCapability,
)
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

CREATE_MAINTENANCE_TICKET_TOOL_NAME = "create_maintenance_ticket"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class TroubleshootingGraphState(TypedDict):
    """Public run result with project-owned types restored after graph execution."""

    messages: Annotated[list[AnyMessage], add_messages]
    executed_tool_count: int
    executed_tool_calls: tuple[ExecutedToolCall, ...]
    run_status: AgentRunStatus | None
    final_answer: str | None
    pending_action: dict[str, str] | None
    approval_result: ApprovalDecision | None
    model_profile_name: str
    run_classification: DataClassification | None


class CheckpointedTroubleshootingGraphState(TypedDict):
    """LangGraph checkpoint state restricted to serializer-safe primitives."""

    messages: Annotated[list[AnyMessage], add_messages]
    executed_tool_count: int
    executed_tool_calls: tuple[dict[str, object], ...]
    run_status: str | None
    final_answer: str | None
    pending_action: dict[str, str] | None
    approval_result: str | None
    model_profile_name: str
    run_classification: int | None


class LangGraphTroubleshootingAgent:
    def __init__(
        self,
        chat_model: LangChainChatModel,
        product_history: ProductHistoryCapability,
        machine_status: MachineStatusCapability,
        maintenance_ticket: MaintenanceTicketCapability | None = None,
        *,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        run_classification: DataClassification | None = None,
        mcp_tool_provider: McpToolProvider | None = None,
    ) -> None:
        self._product_history = product_history
        self._machine_status = machine_status
        self._maintenance_ticket = maintenance_ticket
        self._checkpointer = checkpointer
        self._run_classification = run_classification
        self._mcp_tool_provider = mcp_tool_provider
        self._tools = self._create_direct_tools()
        self._tools_by_name = {tool.name: tool for tool in self._tools}
        self._chat_model = chat_model.bind_tools(self._tools)
        self._graph = self._build_graph(self._chat_model, self._tools_by_name)

    def request_tool_selection(self, user_request: str) -> LLMResponse:
        response = self._chat_model.invoke(self._initial_messages(user_request))
        return to_llm_response(response)

    async def request_tool_selection_via_mcp(
        self,
        user_request: str,
    ) -> LLMResponse:
        """Bind runtime-discovered MCP tools for one first-decision run."""
        async with self._open_mcp_session() as session:
            response = self._chat_model.bind_tools(session.tools).invoke(
                self._initial_messages(user_request)
            )
        return to_llm_response(response)

    def invoke(self, user_request: str) -> TroubleshootingGraphState:
        config: RunnableConfig = {"recursion_limit": 12}
        state = self._graph.invoke(
            self._initial_state(user_request),
            config=config,
        )
        return self._restore_public_state(
            cast(CheckpointedTroubleshootingGraphState, state)
        )

    async def ainvoke_via_mcp(
        self,
        user_request: str,
        *,
        session_observer: Callable[[McpToolSession], None] | None = None,
    ) -> TroubleshootingGraphState:
        """Run the read-only graph path through one MCP session.

        This path deliberately excludes checkpoint resume and MCP write tools. The
        existing synchronous graph retains the ADR-011 approval flow.
        """
        async with self._open_mcp_session() as session:
            if session_observer is not None:
                session_observer(session)
            tools_by_name = {tool.name: tool for tool in session.tools}
            chat_model = self._chat_model.bind_tools(session.tools)
            graph = self._build_async_graph(chat_model, tools_by_name)
            config: RunnableConfig = {"recursion_limit": 12}
            state = await graph.ainvoke(
                self._initial_state(user_request),
                config=config,
            )
        return self._restore_public_state(
            cast(CheckpointedTroubleshootingGraphState, state)
        )

    def start(self, user_request: str, *, thread_id: str) -> TroubleshootingGraphState:
        self._require_resumable_run_context()
        config = self._checkpoint_config(thread_id)
        self._graph.invoke(self._initial_state(user_request), config=config)
        return self.get_checkpointed_state(thread_id=thread_id)

    def resume(
        self,
        *,
        thread_id: str,
        approval: object,
    ) -> TroubleshootingGraphState:
        self._require_resumable_run_context()
        config = self._checkpoint_config(thread_id)
        state = self.get_checkpointed_state(thread_id=thread_id)
        self._require_matching_run_context(state)
        self._graph.invoke(Command(resume=approval), config=config)
        return self.get_checkpointed_state(thread_id=thread_id)

    def get_checkpointed_state(self, *, thread_id: str) -> TroubleshootingGraphState:
        self._require_resumable_run_context()
        snapshot = self._graph.get_state(self._checkpoint_config(thread_id))
        if not snapshot.values:
            raise ValueError(f"No checkpointed run found for thread_id: {thread_id}")
        return self._restore_public_state(
            cast(CheckpointedTroubleshootingGraphState, snapshot.values)
        )

    def get_interrupt_payload(self, *, thread_id: str) -> dict[str, object] | None:
        self._require_resumable_run_context()
        snapshot = self._graph.get_state(self._checkpoint_config(thread_id))
        if not snapshot.interrupts:
            return None
        payload = snapshot.interrupts[0].value
        if not isinstance(payload, dict):
            raise TypeError("Approval interrupt payload must be a dictionary")
        return dict(payload)

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

    async def aanswer_via_mcp(
        self,
        user_request: str,
        *,
        session_observer: Callable[[McpToolSession], None] | None = None,
    ) -> AgentRunResult:
        state = await self.ainvoke_via_mcp(
            user_request,
            session_observer=session_observer,
        )
        run_status = state["run_status"]
        if run_status is None:
            raise RuntimeError("LangGraph MCP run terminated without a status")
        return AgentRunResult(
            status=run_status,
            final_answer=state["final_answer"],
            tool_call_count=state["executed_tool_count"],
            executed_tool_calls=state["executed_tool_calls"],
        )

    def _build_graph(
        self,
        chat_model: LangChainChatModel,
        tools_by_name: dict[str, BaseTool],
    ):
        # noinspection PyTypeChecker
        builder = StateGraph(CheckpointedTroubleshootingGraphState)
        # noinspection PyTypeChecker
        builder.add_node("model", lambda state: self._model_node(chat_model, state))
        # noinspection PyTypeChecker
        builder.add_node("tool", lambda state: self._tool_node(tools_by_name, state))
        # noinspection PyTypeChecker
        builder.add_node("prepare_action", self._prepare_action_node)
        # noinspection PyTypeChecker
        builder.add_node("approval", self._approval_node)
        # noinspection PyTypeChecker
        builder.add_node("execute_action", self._execute_action_node)
        # noinspection PyTypeChecker
        builder.add_node("cancel_action", self._cancel_action_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", self._route_after_model)
        builder.add_edge("tool", "model")
        builder.add_edge("prepare_action", "approval")
        builder.add_conditional_edges("approval", self._route_after_approval)
        builder.add_edge("execute_action", "model")
        builder.add_edge("cancel_action", END)
        return builder.compile(checkpointer=self._checkpointer)

    def _build_async_graph(
        self,
        chat_model: LangChainChatModel,
        tools_by_name: dict[str, BaseTool],
    ):
        async def tool_node(
            state: CheckpointedTroubleshootingGraphState,
        ) -> dict[str, object]:
            return await self._atool_node(tools_by_name, state)

        # noinspection PyTypeChecker
        builder = StateGraph(CheckpointedTroubleshootingGraphState)
        # noinspection PyTypeChecker
        builder.add_node("model", lambda state: self._model_node(chat_model, state))
        # noinspection PyTypeChecker
        builder.add_node("tool", tool_node)
        # The read-only MCP path never advertises this action, but preserving the
        # existing branches keeps a malicious or malformed tool call fail-closed.
        # noinspection PyTypeChecker
        builder.add_node("prepare_action", self._prepare_action_node)
        # noinspection PyTypeChecker
        builder.add_node("approval", self._approval_node)
        # noinspection PyTypeChecker
        builder.add_node("execute_action", self._execute_action_node)
        # noinspection PyTypeChecker
        builder.add_node("cancel_action", self._cancel_action_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", self._route_after_model)
        builder.add_edge("tool", "model")
        builder.add_edge("prepare_action", "approval")
        builder.add_conditional_edges("approval", self._route_after_approval)
        builder.add_edge("execute_action", "model")
        builder.add_edge("cancel_action", END)
        return builder.compile()

    @staticmethod
    def _model_node(
        chat_model: LangChainChatModel,
        state: CheckpointedTroubleshootingGraphState,
    ) -> dict[str, object]:
        message = chat_model.invoke(state["messages"])
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
                "run_status": AgentRunStatus.SUCCESS.value,
                "final_answer": response.text,
            }
        if state["executed_tool_count"] == MAX_TOOL_CALLS:
            return {
                "messages": [message],
                "run_status": AgentRunStatus.LIMIT_REACHED.value,
                "final_answer": None,
            }
        return {"messages": [message]}

    @staticmethod
    def _route_after_model(
        state: CheckpointedTroubleshootingGraphState,
    ) -> Literal["tool", "prepare_action", "__end__"]:
        if state["run_status"] is not None:
            return END
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or len(message.tool_calls) != 1:
            raise RuntimeError("Model route requires exactly one AI tool call")
        if message.tool_calls[0]["name"] == CREATE_MAINTENANCE_TICKET_TOOL_NAME:
            return "prepare_action"
        return "tool"

    @staticmethod
    def _route_after_approval(
        state: CheckpointedTroubleshootingGraphState,
    ) -> Literal["execute_action", "cancel_action"]:
        if state["approval_result"] == ApprovalDecision.APPROVE.value:
            return "execute_action"
        if state["approval_result"] == ApprovalDecision.REJECT.value:
            return "cancel_action"
        raise RuntimeError("Approval node did not produce a valid decision")

    def _tool_node(
        self,
        tools_by_name: dict[str, BaseTool],
        state: CheckpointedTroubleshootingGraphState,
    ) -> dict[str, object]:
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or len(message.tool_calls) != 1:
            raise RuntimeError("Tool node requires exactly one AI tool call")

        tool_call = message.tool_calls[0]
        tool_name = tool_call["name"]
        tool = tools_by_name.get(tool_name)
        if tool is None:
            raise UnknownToolError(f"Unknown tool: {tool_name}")

        arguments = self._validate_tool_arguments(tool_name, dict(tool_call["args"]))
        result = tool.invoke(arguments)
        executed_call = {"tool": tool_name, "arguments": arguments}
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

    async def _atool_node(
        self,
        tools_by_name: dict[str, BaseTool],
        state: CheckpointedTroubleshootingGraphState,
    ) -> dict[str, object]:
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or len(message.tool_calls) != 1:
            raise RuntimeError("Tool node requires exactly one AI tool call")

        tool_call = message.tool_calls[0]
        tool_name = tool_call["name"]
        tool = tools_by_name.get(tool_name)
        if tool is None:
            raise UnknownToolError(f"Unknown tool: {tool_name}")

        arguments = self._validate_tool_arguments(tool_name, dict(tool_call["args"]))
        result = await tool.ainvoke(arguments)
        executed_call = {"tool": tool_name, "arguments": arguments}
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

    def _prepare_action_node(
        self,
        state: CheckpointedTroubleshootingGraphState,
    ) -> dict[str, object]:
        if self._maintenance_ticket is None:
            raise UnknownToolError(
                f"Unknown tool: {CREATE_MAINTENANCE_TICKET_TOOL_NAME}"
            )
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or len(message.tool_calls) != 1:
            raise RuntimeError("Action preparation requires exactly one AI tool call")
        tool_call = message.tool_calls[0]
        if tool_call["name"] != CREATE_MAINTENANCE_TICKET_TOOL_NAME:
            raise UnknownToolError(f"Unknown tool: {tool_call['name']}")
        try:
            arguments = CreateMaintenanceTicketArguments.model_validate(
                dict(tool_call["args"])
            )
        except ValidationError as error:
            raise InvalidToolArgumentsError(
                f"Invalid arguments for {CREATE_MAINTENANCE_TICKET_TOOL_NAME}"
            ) from error
        tool_call_id = _require_tool_call_id(tool_call.get("id"))
        return {
            "pending_action": {
                "action": CREATE_MAINTENANCE_TICKET_TOOL_NAME,
                "request_id": tool_call_id,
                "tool_call_id": tool_call_id,
                "station_id": arguments.station_id,
                "summary": arguments.summary,
            },
            "approval_result": None,
        }

    @staticmethod
    def _approval_node(
        state: CheckpointedTroubleshootingGraphState,
    ) -> dict[str, object]:
        pending_action = _require_pending_action(state)
        approval = _parse_approval(
            interrupt(
                {
                    "kind": "action_approval",
                    "action": pending_action["action"],
                    "details": {
                        "station_id": pending_action["station_id"],
                        "summary": pending_action["summary"],
                    },
                }
            )
        )
        return {"approval_result": approval.value}

    def _execute_action_node(
        self,
        state: CheckpointedTroubleshootingGraphState,
    ) -> dict[str, object]:
        if self._maintenance_ticket is None:
            raise RuntimeError("Maintenance ticket capability is not configured")
        pending_action = _require_pending_action(state)
        if state["approval_result"] != ApprovalDecision.APPROVE.value:
            raise RuntimeError("Maintenance ticket execution requires approval")
        result = self._maintenance_ticket.create_maintenance_ticket(
            request_id=pending_action["request_id"],
            station_id=pending_action["station_id"],
            summary=pending_action["summary"],
        )
        executed_call = {
            "tool": CREATE_MAINTENANCE_TICKET_TOOL_NAME,
            "arguments": {
                "station_id": pending_action["station_id"],
                "summary": pending_action["summary"],
            },
        }
        return {
            "messages": [
                ToolMessage(
                    content=result.model_dump_json(),
                    tool_call_id=pending_action["tool_call_id"],
                )
            ],
            "executed_tool_count": state["executed_tool_count"] + 1,
            "executed_tool_calls": (*state["executed_tool_calls"], executed_call),
            "pending_action": None,
        }

    @staticmethod
    def _cancel_action_node(
        state: CheckpointedTroubleshootingGraphState,
    ) -> dict[str, object]:
        _require_pending_action(state)
        return {
            "pending_action": None,
            "run_status": AgentRunStatus.SUCCESS.value,
            "final_answer": "Maintenance ticket creation was rejected; no ticket was created.",
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

    def _create_direct_tools(self) -> tuple[BaseTool, ...]:
        def get_product_history(product_id: str) -> str:
            result = self._product_history.get_product_history(product_id)
            return result.model_dump_json()

        def get_machine_status(station_id: str) -> str:
            result = self._machine_status.get_machine_status(station_id)
            return result.model_dump_json()

        tools: list[BaseTool] = [
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
        ]
        if self._maintenance_ticket is not None:
            tools.append(
                StructuredTool.from_function(
                    func=lambda station_id, summary: (
                        "Approval required before execution."
                    ),
                    name=CREATE_MAINTENANCE_TICKET_TOOL_NAME,
                    description=(
                        "Propose a maintenance ticket for a station. The ticket is only "
                        "created after explicit human approval."
                    ),
                    args_schema=CreateMaintenanceTicketArguments,
                )
            )
        return tuple(tools)

    @asynccontextmanager
    async def _open_mcp_session(self) -> AsyncIterator[McpToolSession]:
        if self._mcp_tool_provider is None:
            raise RuntimeError("LangGraph MCP execution requires an MCP tool provider")
        async with self._mcp_tool_provider.open_session() as session:
            yield session

    def _initial_state(
        self, user_request: str
    ) -> CheckpointedTroubleshootingGraphState:
        return {
            "messages": self._initial_messages(user_request),
            "executed_tool_count": 0,
            "executed_tool_calls": (),
            "run_status": None,
            "final_answer": None,
            "pending_action": None,
            "approval_result": None,
            "model_profile_name": self._chat_model.model_profile.name,
            "run_classification": (
                int(self._run_classification)
                if self._run_classification is not None
                else None
            ),
        }

    def _initial_messages(self, user_request: str) -> list[AnyMessage]:
        normalized_request = user_request.strip()
        if not normalized_request:
            raise ValueError("User request must not be empty")
        system_content = TROUBLESHOOTING_SYSTEM_MESSAGE.content
        if system_content is None:
            raise RuntimeError("Troubleshooting system message must contain text")
        messages: list[AnyMessage] = [
            SystemMessage(content=system_content),
            HumanMessage(content=normalized_request),
        ]
        if self._maintenance_ticket is not None:
            messages[0] = SystemMessage(
                content=(
                    f"{system_content} You may propose "
                    f"{CREATE_MAINTENANCE_TICKET_TOOL_NAME} only when the user "
                    "explicitly requests a maintenance ticket or it is necessary to "
                    "complete the requested troubleshooting action. The system requires "
                    "human approval before it creates any ticket."
                )
            )
        return messages

    def _require_resumable_run_context(self) -> None:
        if self._checkpointer is None:
            raise RuntimeError("Resumable runs require a LangGraph checkpointer")
        if self._run_classification is None:
            raise RuntimeError("Resumable runs require an explicit data classification")

    def _require_matching_run_context(self, state: TroubleshootingGraphState) -> None:
        if state["model_profile_name"] != self._chat_model.model_profile.name:
            raise RuntimeError(
                "Resumed run model profile does not match the checkpoint"
            )
        if state["run_classification"] is not self._run_classification:
            raise RuntimeError(
                "Resumed run data classification does not match the checkpoint"
            )

    @staticmethod
    def _restore_public_state(
        state: CheckpointedTroubleshootingGraphState,
    ) -> TroubleshootingGraphState:
        raw_status = state["run_status"]
        raw_approval = state["approval_result"]
        raw_classification = state["run_classification"]
        return {
            "messages": state["messages"],
            "executed_tool_count": state["executed_tool_count"],
            "executed_tool_calls": tuple(
                ExecutedToolCall.model_validate(call)
                for call in state["executed_tool_calls"]
            ),
            "run_status": AgentRunStatus(raw_status)
            if raw_status is not None
            else None,
            "final_answer": state["final_answer"],
            "pending_action": state["pending_action"],
            "approval_result": (
                ApprovalDecision(raw_approval) if raw_approval is not None else None
            ),
            "model_profile_name": state["model_profile_name"],
            "run_classification": (
                DataClassification(raw_classification)
                if raw_classification is not None
                else None
            ),
        }

    @staticmethod
    def _checkpoint_config(thread_id: str) -> RunnableConfig:
        normalized_thread_id = thread_id.strip()
        if not normalized_thread_id:
            raise ValueError("thread_id must not be empty")
        return {
            "recursion_limit": 20,
            "configurable": {"thread_id": normalized_thread_id},
        }


def _require_tool_call_id(tool_call_id: object | None) -> str:
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ValueError("Tool call requires a non-empty ID")
    return tool_call_id


def _require_pending_action(
    state: CheckpointedTroubleshootingGraphState,
) -> dict[str, str]:
    pending_action = state["pending_action"]
    if pending_action is None:
        raise RuntimeError("Approval flow requires a pending action")
    return pending_action


def _parse_approval(value: object) -> ApprovalDecision:
    if value == ApprovalDecision.APPROVE.value:
        return ApprovalDecision.APPROVE
    if value == ApprovalDecision.REJECT.value:
        return ApprovalDecision.REJECT
    raise ValueError("Approval must be either 'approve' or 'reject'")
