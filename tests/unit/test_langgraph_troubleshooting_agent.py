from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressDeniedError,
)
from industrial_ai_agent.agent.troubleshooting_agent import (
    MAX_TOOL_CALLS,
    AgentRunStatus,
    InvalidToolArgumentsError,
    ToolCallLimitExceededError,
    TroubleshootingAgent,
    UnknownToolError,
)
from industrial_ai_agent.domain.machine_status import MachineStatus
from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    StationId,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

DEFAULT_PROFILE = ModelProfile("troubleshooting")


class FakeLLMClient:
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[ModelProfile, LLMRequest]] = []

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        self.requests.append((profile, request))
        if not self._responses:
            raise AssertionError("Unexpected LLM call")
        return self._responses.pop(0)


@dataclass
class RecordingProductHistoryRepository:
    requested_ids: list[ProductId] = field(default_factory=list)

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        self.requested_ids.append(product_id)
        return None


@dataclass
class RecordingMachineStatusRepository:
    requested_ids: list[StationId] = field(default_factory=list)

    def get_machine_status(self, station_id: StationId) -> MachineStatus | None:
        self.requested_ids.append(station_id)
        return None


@dataclass(frozen=True)
class StaticExecutionZoneResolver:
    zone: ExecutionZone

    def get_execution_zone(self, profile_name: str) -> ExecutionZone:
        del profile_name
        return self.zone


def tool_call(
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


def final_response(text: str = "Investigation complete.") -> LLMResponse:
    return LLMResponse(text=text, finish_reason=FinishReason.STOP)


def create_graph_agent(
    llm_client: FakeLLMClient | EgressCheckedLLMClient,
    *,
    profile: ModelProfile = DEFAULT_PROFILE,
) -> tuple[
    LangGraphTroubleshootingAgent,
    RecordingProductHistoryRepository,
    RecordingMachineStatusRepository,
]:
    product_repository = RecordingProductHistoryRepository()
    machine_repository = RecordingMachineStatusRepository()
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(llm_client, profile),
        ProductHistoryCapability(product_repository),
        MachineStatusCapability(machine_repository),
    )
    return agent, product_repository, machine_repository


def test_direct_final_answer_terminates_successfully() -> None:
    llm_client = FakeLLMClient(final_response("Provide an identifier."))
    agent, product_repository, machine_repository = create_graph_agent(llm_client)

    result = agent.answer("Can you help?")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "Provide an identifier."
    assert result.tool_call_count == 0
    assert product_repository.requested_ids == []
    assert machine_repository.requested_ids == []


def test_one_tool_call_then_final_answer_succeeds() -> None:
    llm_client = FakeLLMClient(tool_response(tool_call()), final_response())
    agent, product_repository, _ = create_graph_agent(llm_client)

    result = agent.answer("Show P4711 history")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.tool_call_count == 1
    assert result.executed_tool_calls[0].tool == "get_product_history"
    assert product_repository.requested_ids == [ProductId("P4711")]


def test_two_sequential_tool_calls_preserve_order() -> None:
    responses = (
        tool_response(tool_call(call_id="product")),
        tool_response(
            tool_call(
                "get_machine_status",
                {"station_id": "S04"},
                "machine",
            )
        ),
        final_response(),
    )
    llm_client = FakeLLMClient(*responses)
    agent, product_repository, machine_repository = create_graph_agent(llm_client)

    result = agent.answer("Investigate P4711 and its station")

    assert [call.tool for call in result.executed_tool_calls] == [
        "get_product_history",
        "get_machine_status",
    ]
    assert product_repository.requested_ids == [ProductId("P4711")]
    assert machine_repository.requested_ids == [StationId("S04")]


def test_three_tool_calls_can_still_end_with_success() -> None:
    llm_client = FakeLLMClient(
        tool_response(tool_call(call_id="call-1")),
        tool_response(tool_call(call_id="call-2")),
        tool_response(tool_call(call_id="call-3")),
        final_response(),
    )
    agent, product_repository, _ = create_graph_agent(llm_client)

    result = agent.answer("Inspect all evidence")

    assert result.status is AgentRunStatus.SUCCESS
    assert result.tool_call_count == MAX_TOOL_CALLS
    assert len(product_repository.requested_ids) == MAX_TOOL_CALLS
    assert len(llm_client.requests) == 4


def test_fourth_requested_tool_is_not_executed_and_no_later_model_call_occurs() -> None:
    llm_client = FakeLLMClient(
        tool_response(tool_call(call_id="call-1")),
        tool_response(tool_call(call_id="call-2")),
        tool_response(tool_call(call_id="call-3")),
        tool_response(
            tool_call(
                "get_machine_status",
                {"station_id": "S04"},
                "call-4",
            )
        ),
        final_response("Must not be requested"),
    )
    agent, product_repository, machine_repository = create_graph_agent(llm_client)

    state = agent.invoke("Keep calling tools")

    assert state["run_status"] is AgentRunStatus.LIMIT_REACHED
    assert state["executed_tool_count"] == MAX_TOOL_CALLS
    assert len(product_repository.requested_ids) == MAX_TOOL_CALLS
    assert machine_repository.requested_ids == []
    assert len(llm_client.requests) == 4


def test_unknown_tool_is_rejected_before_capability_execution() -> None:
    llm_client = FakeLLMClient(
        tool_response(tool_call("restart_station", {"station_id": "S04"}))
    )
    agent, product_repository, machine_repository = create_graph_agent(llm_client)

    with pytest.raises(UnknownToolError, match="Unknown tool: restart_station"):
        agent.answer("Restart S04")

    assert product_repository.requested_ids == []
    assert machine_repository.requested_ids == []


def test_invalid_tool_arguments_are_rejected_before_capability_execution() -> None:
    llm_client = FakeLLMClient(tool_response(tool_call(arguments={})))
    agent, product_repository, machine_repository = create_graph_agent(llm_client)

    with pytest.raises(
        InvalidToolArgumentsError,
        match="Invalid arguments for get_product_history",
    ):
        agent.answer("Inspect product")

    assert product_repository.requested_ids == []
    assert machine_repository.requested_ids == []


def test_multiple_tool_calls_are_rejected_before_execution() -> None:
    llm_client = FakeLLMClient(
        tool_response(
            tool_call(call_id="product"),
            tool_call(
                "get_machine_status",
                {"station_id": "S04"},
                "machine",
            ),
        )
    )
    agent, product_repository, machine_repository = create_graph_agent(llm_client)

    with pytest.raises(
        ToolCallLimitExceededError,
        match="At most one tool call per LLM response",
    ):
        agent.answer("Inspect both")

    assert product_repository.requested_ids == []
    assert machine_repository.requested_ids == []


def test_selected_profile_is_injected_and_langchain_tools_are_bound() -> None:
    selected_profile = ModelProfile("selected-by-composition-root")
    llm_client = FakeLLMClient(final_response())
    agent, _, _ = create_graph_agent(llm_client, profile=selected_profile)

    agent.answer("Finish directly")

    profile, request = llm_client.requests[0]
    assert profile == selected_profile
    assert [tool.name for tool in request.tools] == [
        "get_product_history",
        "get_machine_status",
    ]


def test_confidential_public_cloud_request_is_denied_before_adapter_call() -> None:
    adapter = FakeLLMClient(final_response())
    checked_client = EgressCheckedLLMClient(
        adapter,
        StaticExecutionZoneResolver(ExecutionZone.PUBLIC_CLOUD),
        DataClassification.CONFIDENTIAL,
    )
    agent, _, _ = create_graph_agent(
        checked_client,
        profile=ModelProfile("public_fast"),
    )

    with pytest.raises(ModelEgressDeniedError, match="Model egress denied by policy"):
        agent.answer("Synthetic request")

    assert adapter.requests == []


@pytest.mark.parametrize(
    "responses",
    [
        (final_response("Direct"),),
        (tool_response(tool_call()), final_response("One tool")),
        (
            tool_response(tool_call(call_id="product")),
            tool_response(
                tool_call(
                    "get_machine_status",
                    {"station_id": "S04"},
                    "machine",
                )
            ),
            final_response("Two tools"),
        ),
    ],
    ids=["direct", "one-tool", "two-tools"],
)
def test_manual_and_langgraph_paths_are_behaviorally_equivalent(
    responses: tuple[LLMResponse, ...],
) -> None:
    manual_client = FakeLLMClient(*responses)
    graph_client = FakeLLMClient(*responses)
    manual_product = RecordingProductHistoryRepository()
    manual_machine = RecordingMachineStatusRepository()
    manual_agent = TroubleshootingAgent(
        manual_client,
        ProductHistoryCapability(manual_product),
        MachineStatusCapability(manual_machine),
    )
    graph_agent, _, _ = create_graph_agent(graph_client)

    manual_result = manual_agent.answer("Run equivalent trajectory")
    graph_result = graph_agent.answer("Run equivalent trajectory")

    assert graph_result.status is manual_result.status
    assert graph_result.executed_tool_calls == manual_result.executed_tool_calls
    assert graph_result.tool_call_count == manual_result.tool_call_count
    assert (graph_result.final_answer is not None) is (
        manual_result.final_answer is not None
    )
    assert graph_result.final_answer == manual_result.final_answer
