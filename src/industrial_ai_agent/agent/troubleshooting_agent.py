from enum import StrEnum
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

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
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

TROUBLESHOOTING_PROFILE = ModelProfile("troubleshooting")
MAX_TOOL_CALLS = 3
GET_PRODUCT_HISTORY_TOOL = LLMToolDefinition(
    name="get_product_history",
    description=(
        "Retrieve the chronological production history for a product by its unique "
        "product ID."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "product_id": {
                "type": "string",
                "description": "The unique product ID, for example P4711.",
            }
        },
        "required": ["product_id"],
    },
)
GET_MACHINE_STATUS_TOOL = LLMToolDefinition(
    name="get_machine_status",
    description=(
        "Retrieve the current operational status of a machine station by its unique "
        "station ID."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "station_id": {
                "type": "string",
                "description": "The unique station ID, for example S04.",
            }
        },
        "required": ["station_id"],
    },
)
_SYSTEM_MESSAGE = LLMMessage(
    role=MessageRole.SYSTEM,
    content=(
        "You are an industrial troubleshooting assistant. Use get_product_history "
        "for questions about a product's production history and get_machine_status "
        "for questions about a station's current operational status. Call one tool at "
        "a time. After each tool result, decide whether another tool is needed or a "
        "final answer is possible. When investigating a product failure and the "
        "current status of its relevant station, first retrieve the product history, "
        "then use the station ID from the failed step to retrieve the machine status. "
        "Do not repeat a tool call whose result is already available. Base the final "
        "answer on the collected tool results and do not invent industrial data."
    ),
)


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


class ProductHistoryToolArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, product_id: str) -> str:
        normalized_product_id = product_id.strip()
        if not normalized_product_id:
            raise ValueError("product_id must not be empty")
        return normalized_product_id


class MachineStatusToolArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    station_id: str

    @field_validator("station_id")
    @classmethod
    def validate_station_id(cls, station_id: str) -> str:
        normalized_station_id = station_id.strip()
        if not normalized_station_id:
            raise ValueError("station_id must not be empty")
        return normalized_station_id


class TroubleshootingAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        product_history: ProductHistoryCapability,
        machine_status: MachineStatusCapability,
        model_profile: ModelProfile = TROUBLESHOOTING_PROFILE,
    ) -> None:
        self._llm_client = llm_client
        self._product_history = product_history
        self._machine_status = machine_status
        self._model_profile = model_profile

    def request_tool_selection(self, user_request: str) -> LLMResponse:
        user_message = _create_user_message(user_request)
        return self._request_tool_selection(user_message)

    def answer(self, user_request: str) -> AgentRunResult:
        user_message = _create_user_message(user_request)
        messages = [_SYSTEM_MESSAGE, user_message]
        executed_tool_calls: list[ExecutedToolCall] = []

        while True:
            response = self._request_decision(tuple(messages))
            if not response.tool_calls:
                return AgentRunResult(
                    status=AgentRunStatus.SUCCESS,
                    final_answer=_require_response_text(response),
                    tool_call_count=len(executed_tool_calls),
                    executed_tool_calls=tuple(executed_tool_calls),
                )
            if len(response.tool_calls) > 1:
                raise ToolCallLimitExceededError(
                    "At most one tool call per LLM response is allowed"
                )
            if len(executed_tool_calls) == MAX_TOOL_CALLS:
                return AgentRunResult(
                    status=AgentRunStatus.LIMIT_REACHED,
                    tool_call_count=len(executed_tool_calls),
                    executed_tool_calls=tuple(executed_tool_calls),
                )

            tool_call = response.tool_calls[0]
            tool_result, executed_tool_call = self._dispatch_tool_call(tool_call)
            messages.extend(
                (
                    LLMMessage(
                        role=MessageRole.ASSISTANT,
                        content=response.text,
                        tool_calls=(tool_call,),
                    ),
                    LLMMessage(
                        role=MessageRole.TOOL,
                        content=tool_result,
                        tool_call_id=tool_call.id,
                    ),
                )
            )
            executed_tool_calls.append(executed_tool_call)

    def _request_tool_selection(self, user_message: LLMMessage) -> LLMResponse:
        return self._request_decision((_SYSTEM_MESSAGE, user_message))

    def _request_decision(self, messages: tuple[LLMMessage, ...]) -> LLMResponse:
        return self._llm_client.chat(
            self._model_profile,
            LLMRequest(
                messages=messages,
                tools=(GET_PRODUCT_HISTORY_TOOL, GET_MACHINE_STATUS_TOOL),
            ),
        )

    def _dispatch_tool_call(
        self, tool_call: LLMToolCall
    ) -> tuple[str, ExecutedToolCall]:
        if tool_call.name == GET_PRODUCT_HISTORY_TOOL.name:
            try:
                arguments = ProductHistoryToolArguments.model_validate(
                    tool_call.arguments
                )
            except ValidationError as error:
                raise InvalidToolArgumentsError(
                    f"Invalid arguments for {GET_PRODUCT_HISTORY_TOOL.name}"
                ) from error

            result = self._product_history.get_product_history(arguments.product_id)
            return result.model_dump_json(), ExecutedToolCall(
                tool=GET_PRODUCT_HISTORY_TOOL.name,
                arguments={"product_id": arguments.product_id},
            )

        if tool_call.name == GET_MACHINE_STATUS_TOOL.name:
            try:
                arguments = MachineStatusToolArguments.model_validate(
                    tool_call.arguments
                )
            except ValidationError as error:
                raise InvalidToolArgumentsError(
                    f"Invalid arguments for {GET_MACHINE_STATUS_TOOL.name}"
                ) from error

            result = self._machine_status.get_machine_status(arguments.station_id)
            return result.model_dump_json(), ExecutedToolCall(
                tool=GET_MACHINE_STATUS_TOOL.name,
                arguments={"station_id": arguments.station_id},
            )

        raise UnknownToolError(f"Unknown tool: {tool_call.name}")


def _require_response_text(response: LLMResponse) -> str:
    if response.text is None:
        raise MissingLLMResponseTextError("LLM response did not contain text")
    return response.text


def _create_user_message(user_request: str) -> LLMMessage:
    normalized_request = user_request.strip()
    if not normalized_request:
        raise ValueError("User request must not be empty")
    return LLMMessage(
        role=MessageRole.USER,
        content=normalized_request,
    )
