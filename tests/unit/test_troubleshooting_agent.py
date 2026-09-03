import json
from datetime import UTC, datetime

import pytest

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.agent.troubleshooting_agent import (
    MAX_TOOL_CALLS,
    AgentRunStatus,
    ExecutedToolCall,
    InvalidToolArgumentsError,
    ToolCallLimitExceededError,
    TroubleshootingAgent,
    UnknownToolError,
)
from industrial_ai_agent.domain.machine_status import MachineState, MachineStatus
from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    ProductionStep,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
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


class RecordingMachineStatusRepository:
    def __init__(self) -> None:
        self.requested_station_ids: list[StationId] = []

    def get_machine_status(self, station_id: StationId) -> MachineStatus | None:
        self.requested_station_ids.append(station_id)
        if station_id != StationId("S04"):
            return None
        return MachineStatus(
            station_id=station_id,
            state=MachineState.FAULTED,
            active_error_code="E-STOP-17",
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


def final_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        finish_reason=FinishReason.STOP,
    )


def create_agent(
    llm_client: FakeLLMClient,
) -> tuple[
    TroubleshootingAgent,
    RecordingProductHistoryRepository,
    RecordingMachineStatusRepository,
]:
    product_repository = RecordingProductHistoryRepository()
    machine_repository = RecordingMachineStatusRepository()
    agent = TroubleshootingAgent(
        llm_client,
        ProductHistoryCapability(product_repository),
        MachineStatusCapability(machine_repository),
    )
    return agent, product_repository, machine_repository


def test_request_tool_selection_uses_profile_without_executing_tool() -> None:
    requested_tool_call = tool_call(arguments={"product_id": "P4711"})
    initial_response = tool_response(requested_tool_call)
    llm_client = FakeLLMClient(initial_response)
    product_repository = RecordingProductHistoryRepository()
    machine_repository = RecordingMachineStatusRepository()
    agent = TroubleshootingAgent(
        llm_client,
        ProductHistoryCapability(product_repository),
        MachineStatusCapability(machine_repository),
        model_profile=ModelProfile("evaluation-candidate"),
    )

    response = agent.request_tool_selection("Why was product P4711 rejected?")

    assert response == initial_response
    assert len(llm_client.requests) == 1
    assert llm_client.requests[0][0] == ModelProfile("evaluation-candidate")
    assert product_repository.requested_product_ids == []
    assert machine_repository.requested_station_ids == []


def test_product_question_executes_product_history_and_returns_final_answer() -> None:
    requested_tool_call = tool_call(arguments={"product_id": "P4711"})
    llm_client = FakeLLMClient(
        tool_response(requested_tool_call),
        final_response("P4711 failed at S04 with E-STOP-17."),
    )
    agent, product_repository, machine_repository = create_agent(llm_client)

    result = agent.answer("Why was product P4711 rejected?")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "P4711 failed at S04 with E-STOP-17."
    assert result.tool_call_count == 1
    assert product_repository.requested_product_ids == [ProductId("P4711")]
    assert machine_repository.requested_station_ids == []
    assert len(llm_client.requests) == 2
    assert [profile.name for profile, _ in llm_client.requests] == [
        "troubleshooting",
        "troubleshooting",
    ]

    initial_request = llm_client.requests[0][1]
    assert [tool.name for tool in initial_request.tools] == [
        "get_product_history",
        "get_machine_status",
    ]
    assert initial_request.tools[0].parameters["required"] == ["product_id"]

    follow_up_request = llm_client.requests[1][1]
    assert [tool.name for tool in follow_up_request.tools] == [
        "get_product_history",
        "get_machine_status",
    ]
    assert follow_up_request.messages[-2].tool_calls == (requested_tool_call,)
    assert follow_up_request.messages[-1].tool_call_id == "call-1"
    tool_result = json.loads(follow_up_request.messages[-1].content or "")
    assert tool_result["product_id"] == "P4711"
    assert tool_result["found"] is True
    assert tool_result["steps"][0]["error_code"] == "E-STOP-17"


def test_station_question_executes_machine_status_with_correct_station_id() -> None:
    requested_tool_call = tool_call(
        name="get_machine_status",
        arguments={"station_id": "S04"},
    )
    llm_client = FakeLLMClient(
        tool_response(requested_tool_call),
        final_response("Station S04 is faulted with E-STOP-17."),
    )
    agent, product_repository, machine_repository = create_agent(llm_client)

    result = agent.answer("What is the current status of station S04?")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "Station S04 is faulted with E-STOP-17."
    assert result.tool_call_count == 1
    assert product_repository.requested_product_ids == []
    assert machine_repository.requested_station_ids == [StationId("S04")]

    initial_request = llm_client.requests[0][1]
    assert initial_request.tools[1].parameters == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "station_id": {
                "type": "string",
                "description": "The unique station ID, for example S04.",
            }
        },
        "required": ["station_id"],
    }
    tool_result = json.loads(llm_client.requests[1][1].messages[-1].content or "")
    assert tool_result == {
        "station_id": "S04",
        "found": True,
        "state": "FAULTED",
        "active_error_code": "E-STOP-17",
    }


def test_unknown_station_returns_structured_not_found_result_to_llm() -> None:
    llm_client = FakeLLMClient(
        tool_response(
            tool_call(
                name="get_machine_status",
                arguments={"station_id": "S99"},
            )
        ),
        final_response("No current status is available for station S99."),
    )
    agent, _, machine_repository = create_agent(llm_client)

    result = agent.answer("What is the current status of station S99?")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "No current status is available for station S99."
    assert result.tool_call_count == 1
    assert machine_repository.requested_station_ids == [StationId("S99")]
    tool_result = json.loads(llm_client.requests[1][1].messages[-1].content or "")
    assert tool_result == {
        "station_id": "S99",
        "found": False,
        "state": None,
        "active_error_code": None,
    }


def test_returns_direct_answer_without_tool_call() -> None:
    llm_client = FakeLLMClient(final_response("Please provide an identifier."))
    agent, product_repository, machine_repository = create_agent(llm_client)

    result = agent.answer("Can you help me?")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "Please provide an identifier."
    assert result.tool_call_count == 0
    assert product_repository.requested_product_ids == []
    assert machine_repository.requested_station_ids == []
    assert len(llm_client.requests) == 1


def test_rejects_unknown_tool_name() -> None:
    llm_client = FakeLLMClient(
        tool_response(
            tool_call(name="restart_station", arguments={"station_id": "S04"})
        )
    )
    agent, product_repository, machine_repository = create_agent(llm_client)

    with pytest.raises(UnknownToolError, match="Unknown tool: restart_station"):
        agent.answer("Restart the station")

    assert product_repository.requested_product_ids == []
    assert machine_repository.requested_station_ids == []


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_product_history", {}),
        ("get_product_history", {"product_id": ""}),
        ("get_product_history", {"station_id": "S04"}),
        ("get_machine_status", {}),
        ("get_machine_status", {"station_id": ""}),
        ("get_machine_status", {"product_id": "P4711"}),
    ],
)
def test_rejects_invalid_or_missing_tool_arguments(
    name: str,
    arguments: dict[str, object],
) -> None:
    llm_client = FakeLLMClient(tool_response(tool_call(name=name, arguments=arguments)))
    agent, product_repository, machine_repository = create_agent(llm_client)

    with pytest.raises(
        InvalidToolArgumentsError,
        match=f"Invalid arguments for {name}",
    ):
        agent.answer("Inspect the asset")

    assert product_repository.requested_product_ids == []
    assert machine_repository.requested_station_ids == []


def test_rejects_multiple_tool_calls_before_execution() -> None:
    llm_client = FakeLLMClient(
        tool_response(
            tool_call(call_id="call-1"),
            tool_call(
                name="get_machine_status",
                arguments={"station_id": "S04"},
                call_id="call-2",
            ),
        )
    )
    agent, product_repository, machine_repository = create_agent(llm_client)

    with pytest.raises(
        ToolCallLimitExceededError,
        match="At most one tool call per LLM response",
    ):
        agent.answer("Inspect P4711 and S04")

    assert product_repository.requested_product_ids == []
    assert machine_repository.requested_station_ids == []


def test_executes_two_sequential_tool_calls_and_preserves_observations() -> None:
    product_call = tool_call(call_id="call-product")
    machine_call = tool_call(
        name="get_machine_status",
        arguments={"station_id": "S04"},
        call_id="call-machine",
    )
    llm_client = FakeLLMClient(
        tool_response(product_call),
        tool_response(machine_call),
        final_response("P4711 failed at S04, which is currently faulted."),
    )
    agent, product_repository, machine_repository = create_agent(llm_client)

    result = agent.answer("Investigate P4711 and check the relevant station.")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "P4711 failed at S04, which is currently faulted."
    assert result.tool_call_count == 2
    assert result.executed_tool_calls == (
        ExecutedToolCall(
            tool="get_product_history",
            arguments={"product_id": "P4711"},
        ),
        ExecutedToolCall(
            tool="get_machine_status",
            arguments={"station_id": "S04"},
        ),
    )
    assert product_repository.requested_product_ids == [ProductId("P4711")]
    assert machine_repository.requested_station_ids == [StationId("S04")]
    assert len(llm_client.requests) == 3

    second_request = llm_client.requests[1][1]
    assert second_request.messages[-2].role is MessageRole.ASSISTANT
    assert second_request.messages[-2].tool_calls == (product_call,)
    assert second_request.messages[-1].role is MessageRole.TOOL
    assert second_request.messages[-1].tool_call_id == "call-product"
    first_observation = json.loads(second_request.messages[-1].content or "")
    assert first_observation["product_id"] == "P4711"
    assert first_observation["steps"][0]["station_id"] == "S04"

    final_request = llm_client.requests[2][1]
    assert final_request.messages[-4:] == (
        second_request.messages[-2],
        second_request.messages[-1],
        final_request.messages[-2],
        final_request.messages[-1],
    )
    assert final_request.messages[-2].tool_calls == (machine_call,)
    assert final_request.messages[-1].tool_call_id == "call-machine"
    second_observation = json.loads(final_request.messages[-1].content or "")
    assert second_observation == {
        "station_id": "S04",
        "found": True,
        "state": "FAULTED",
        "active_error_code": "E-STOP-17",
    }


def test_executes_three_tool_calls_before_success() -> None:
    llm_client = FakeLLMClient(
        tool_response(tool_call(call_id="call-1")),
        tool_response(
            tool_call(
                name="get_machine_status",
                arguments={"station_id": "S04"},
                call_id="call-2",
            )
        ),
        tool_response(tool_call(call_id="call-3")),
        final_response("Investigation complete."),
    )
    agent, product_repository, machine_repository = create_agent(llm_client)

    result = agent.answer("Investigate all available evidence.")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "Investigation complete."
    assert result.tool_call_count == MAX_TOOL_CALLS
    assert len(result.executed_tool_calls) == MAX_TOOL_CALLS
    assert product_repository.requested_product_ids == [
        ProductId("P4711"),
        ProductId("P4711"),
    ]
    assert machine_repository.requested_station_ids == [StationId("S04")]
    assert len(llm_client.requests) == 4


def test_returns_limit_reached_without_executing_fourth_call_or_calling_llm_again() -> (
    None
):
    llm_client = FakeLLMClient(
        tool_response(tool_call(call_id="call-1")),
        tool_response(tool_call(call_id="call-2")),
        tool_response(tool_call(call_id="call-3")),
        tool_response(
            tool_call(
                name="get_machine_status",
                arguments={"station_id": "S04"},
                call_id="call-4",
            )
        ),
        final_response("This response must never be requested."),
    )
    agent, product_repository, machine_repository = create_agent(llm_client)

    result = agent.answer("Keep investigating indefinitely.")

    assert result.status is AgentRunStatus.LIMIT_REACHED
    assert result.final_answer is None
    assert result.tool_call_count == MAX_TOOL_CALLS
    assert (
        result.executed_tool_calls
        == (
            ExecutedToolCall(
                tool="get_product_history",
                arguments={"product_id": "P4711"},
            ),
        )
        * MAX_TOOL_CALLS
    )
    assert product_repository.requested_product_ids == [ProductId("P4711")] * 3
    assert machine_repository.requested_station_ids == []
    assert len(llm_client.requests) == 4


def test_tool_counter_counts_executed_tools_instead_of_llm_calls() -> None:
    llm_client = FakeLLMClient(
        tool_response(tool_call(call_id="call-1")),
        tool_response(
            tool_call(
                name="get_machine_status",
                arguments={"station_id": "S04"},
                call_id="call-2",
            )
        ),
        final_response("Done."),
    )
    agent, _, _ = create_agent(llm_client)

    result = agent.answer("Investigate P4711 and its station.")

    assert result.tool_call_count == 2
    assert len(llm_client.requests) == 3
    assert result.status is not AgentRunStatus.LIMIT_REACHED
