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
_SYSTEM_MESSAGE = LLMMessage(
    role=MessageRole.SYSTEM,
    content=(
        "You are an industrial troubleshooting assistant. Use the provided tool when "
        "production history is needed. Base the final answer on the tool result and "
        "do not invent production data."
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


class ProductHistoryAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        product_history: ProductHistoryCapability,
    ) -> None:
        self._llm_client = llm_client
        self._product_history = product_history

    def answer(self, user_request: str) -> str:
        normalized_request = user_request.strip()
        if not normalized_request:
            raise ValueError("User request must not be empty")

        user_message = LLMMessage(
            role=MessageRole.USER,
            content=normalized_request,
        )
        initial_response = self._llm_client.chat(
            TROUBLESHOOTING_PROFILE,
            LLMRequest(
                messages=(_SYSTEM_MESSAGE, user_message),
                tools=(GET_PRODUCT_HISTORY_TOOL,),
            ),
        )

        if not initial_response.tool_calls:
            return _require_response_text(initial_response)
        if len(initial_response.tool_calls) > 1:
            raise ToolCallLimitExceededError("At most one tool call is allowed")

        tool_call = initial_response.tool_calls[0]
        tool_result = self._dispatch_tool_call(tool_call)
        final_response = self._llm_client.chat(
            TROUBLESHOOTING_PROFILE,
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

    def _dispatch_tool_call(self, tool_call: LLMToolCall) -> str:
        if tool_call.name != GET_PRODUCT_HISTORY_TOOL.name:
            raise UnknownToolError(f"Unknown tool: {tool_call.name}")

        try:
            arguments = ProductHistoryToolArguments.model_validate(tool_call.arguments)
        except ValidationError as error:
            raise InvalidToolArgumentsError(
                f"Invalid arguments for {GET_PRODUCT_HISTORY_TOOL.name}"
            ) from error

        result = self._product_history.get_product_history(arguments.product_id)
        return result.model_dump_json()


def _require_response_text(response: LLMResponse) -> str:
    if response.text is None:
        raise MissingLLMResponseTextError("LLM response did not contain text")
    return response.text
