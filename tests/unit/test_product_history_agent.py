import json
from datetime import UTC, datetime

import pytest

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.agent.product_history_agent import (
    InvalidToolArgumentsError,
    ProductHistoryAgent,
    ToolCallLimitExceededError,
    UnknownToolError,
)
from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    ProductionStep,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.tools.product_history import ProductHistoryCapability


class FakeLLMClient:
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[ModelProfile, LLMRequest]] = []

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        self.requests.append((profile, request))
        if not self._responses:
            raise AssertionError("Unexpected LLM call")
        return self._responses.pop(0)


class RecordingProductHistoryRepository:
    def __init__(self) -> None:
        self.requested_product_ids: list[ProductId] = []

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        self.requested_product_ids.append(product_id)
        if product_id != ProductId("P4711"):
            return None
        return ProductHistory(
            product_id=product_id,
            steps=(
                ProductionStep(
                    station_id=StationId("S04"),
                    timestamp=datetime(2026, 1, 15, 8, 9, tzinfo=UTC),
                    status=ProductionStepStatus.FAILED,
                    error_code="E-STOP-17",
                ),
            ),
        )


def tool_call(
    *,
    name: str = "get_product_history",
    arguments: dict[str, object] | None = None,
    call_id: str = "call-1",
) -> LLMToolCall:
    return LLMToolCall(
        id=call_id,
        name=name,
        arguments=arguments if arguments is not None else {"product_id": "P4711"},
    )


def tool_response(*tool_calls: LLMToolCall) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=tool_calls,
        finish_reason=FinishReason.TOOL_CALLS,
    )


def final_response(text: str = "P4711 was rejected at station S04.") -> LLMResponse:
    return LLMResponse(
        text=text,
        finish_reason=FinishReason.STOP,
    )


def create_agent(
    llm_client: FakeLLMClient,
) -> tuple[ProductHistoryAgent, RecordingProductHistoryRepository]:
    repository = RecordingProductHistoryRepository()
    capability = ProductHistoryCapability(repository)
    return ProductHistoryAgent(llm_client, capability), repository


def test_p4711_tool_call_executes_product_history_and_returns_final_answer() -> None:
    requested_tool_call = tool_call(arguments={"product_id": "P4711"})
    llm_client = FakeLLMClient(
        tool_response(requested_tool_call),
        final_response("P4711 failed at S04 with E-STOP-17."),
    )
    agent, repository = create_agent(llm_client)

    answer = agent.answer("Why was product P4711 rejected?")

    assert answer == "P4711 failed at S04 with E-STOP-17."
    assert repository.requested_product_ids == [ProductId("P4711")]
    assert len(llm_client.requests) == 2
    assert llm_client.requests[0][0].name == "troubleshooting"
    assert llm_client.requests[1][0].name == "troubleshooting"

    initial_request = llm_client.requests[0][1]
    assert initial_request.tools[0].name == "get_product_history"
    assert initial_request.tools[0].parameters == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "product_id": {
                "type": "string",
                "description": "The unique product ID, for example P4711.",
            }
        },
        "required": ["product_id"],
    }

    follow_up_request = llm_client.requests[1][1]
    assert follow_up_request.tools == ()
    assert follow_up_request.messages[-2].tool_calls == (requested_tool_call,)
    assert follow_up_request.messages[-1].tool_call_id == "call-1"
    tool_result = json.loads(follow_up_request.messages[-1].content or "")
    assert tool_result["product_id"] == "P4711"
    assert tool_result["found"] is True
    assert tool_result["steps"][0]["error_code"] == "E-STOP-17"


def test_returns_direct_answer_without_tool_call() -> None:
    llm_client = FakeLLMClient(final_response("Please provide a product ID."))
    agent, repository = create_agent(llm_client)

    answer = agent.answer("Can you help me?")

    assert answer == "Please provide a product ID."
    assert repository.requested_product_ids == []
    assert len(llm_client.requests) == 1


def test_rejects_unknown_tool_name() -> None:
    llm_client = FakeLLMClient(tool_response(tool_call(name="restart_station")))
    agent, repository = create_agent(llm_client)

    with pytest.raises(UnknownToolError, match="Unknown tool: restart_station"):
        agent.answer("Restart the station")

    assert repository.requested_product_ids == []


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"product_id": ""},
        {"product_id": "P4711", "unexpected": True},
    ],
)
def test_rejects_invalid_tool_arguments(arguments: dict[str, object]) -> None:
    llm_client = FakeLLMClient(tool_response(tool_call(arguments=arguments)))
    agent, repository = create_agent(llm_client)

    with pytest.raises(
        InvalidToolArgumentsError,
        match="Invalid arguments for get_product_history",
    ):
        agent.answer("Inspect the product")

    assert repository.requested_product_ids == []


def test_rejects_multiple_tool_calls_before_execution() -> None:
    llm_client = FakeLLMClient(
        tool_response(
            tool_call(call_id="call-1"),
            tool_call(call_id="call-2"),
        )
    )
    agent, repository = create_agent(llm_client)

    with pytest.raises(ToolCallLimitExceededError, match="At most one tool call"):
        agent.answer("Inspect P4711 twice")

    assert repository.requested_product_ids == []


def test_rejects_second_tool_call_instead_of_starting_a_loop() -> None:
    llm_client = FakeLLMClient(
        tool_response(tool_call(call_id="call-1")),
        tool_response(tool_call(call_id="call-2")),
    )
    agent, repository = create_agent(llm_client)

    with pytest.raises(
        ToolCallLimitExceededError,
        match="final response must not request another tool call",
    ):
        agent.answer("Why was P4711 rejected?")

    assert repository.requested_product_ids == [ProductId("P4711")]
