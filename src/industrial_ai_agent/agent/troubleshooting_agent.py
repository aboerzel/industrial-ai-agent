from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

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
        "for questions about a station's current operational status. Base the final "
        "answer on the tool result and do not invent industrial data."
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

    def answer(self, user_request: str) -> str:
        user_message = _create_user_message(user_request)
        initial_response = self._request_tool_selection(user_message)

        if not initial_response.tool_calls:
            return _require_response_text(initial_response)
        if len(initial_response.tool_calls) > 1:
            raise ToolCallLimitExceededError("At most one tool call is allowed")

        tool_call = initial_response.tool_calls[0]
        tool_result = self._dispatch_tool_call(tool_call)
        final_response = self._llm_client.chat(
            self._model_profile,
            LLMRequest(
                messages=(
                    _SYSTEM_MESSAGE,
                    user_message,
                    LLMMessage(
                        role=MessageRole.ASSISTANT,
                        content=initial_response.text,
                        tool_calls=(tool_call,),
                    ),
                    LLMMessage(
                        role=MessageRole.TOOL,
                        content=tool_result,
                        tool_call_id=tool_call.id,
                    ),
                ),
            ),
        )
        if final_response.tool_calls:
            raise ToolCallLimitExceededError(
                "The final response must not request another tool call"
            )
        return _require_response_text(final_response)

    def _request_tool_selection(self, user_message: LLMMessage) -> LLMResponse:
        return self._llm_client.chat(
            self._model_profile,
            LLMRequest(
                messages=(_SYSTEM_MESSAGE, user_message),
                tools=(GET_PRODUCT_HISTORY_TOOL, GET_MACHINE_STATUS_TOOL),
            ),
        )

    def _dispatch_tool_call(self, tool_call: LLMToolCall) -> str:
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
            return result.model_dump_json()

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
            return result.model_dump_json()

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
