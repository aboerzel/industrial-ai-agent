from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    CREATE_MAINTENANCE_TICKET_TOOL_NAME,
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
from industrial_ai_agent.agent.troubleshooting_agent import AgentRunStatus
from industrial_ai_agent.domain.machine_status import MachineStatus
from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    StationId,
)
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

DEFAULT_PROFILE = ModelProfile("local_quality")


class FakeLLMClient:
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[ModelProfile, LLMRequest]] = []

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        self.requests.append((profile, request))
        if not self._responses:
            raise AssertionError("Unexpected LLM call")
        return self._responses.pop(0)


@dataclass(frozen=True)
class StaticExecutionZoneResolver:
    zone: ExecutionZone

    def get_execution_zone(self, profile_name: str) -> ExecutionZone:
        del profile_name
        return self.zone


@dataclass
class EmptyProductHistoryRepository:
    requested_ids: list[ProductId] = field(default_factory=list)

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        self.requested_ids.append(product_id)
        return None


@dataclass
class EmptyMachineStatusRepository:
    requested_ids: list[StationId] = field(default_factory=list)

    def get_machine_status(self, station_id: StationId) -> MachineStatus | None:
        self.requested_ids.append(station_id)
        return None


def action_response(
    *,
    station_id: str = "S04",
    summary: str = "Investigate E-STOP-17",
    call_id: str = "ticket-call-1",
) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(
            LLMToolCall(
                id=call_id,
                name=CREATE_MAINTENANCE_TICKET_TOOL_NAME,
                arguments={"station_id": station_id, "summary": summary},
            ),
        ),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def final_response(text: str = "Investigation complete.") -> LLMResponse:
    return LLMResponse(text=text, finish_reason=FinishReason.STOP)


def product_history_response() -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(
            LLMToolCall(
                id="history-call-1",
                name="get_product_history",
                arguments={"product_id": "P4711"},
            ),
        ),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def create_hitl_agent(
    llm_client: FakeLLMClient,
    *,
    checkpointer: InMemorySaver,
    profile: ModelProfile = DEFAULT_PROFILE,
    classification: DataClassification = DataClassification.CONFIDENTIAL,
) -> tuple[LangGraphTroubleshootingAgent, InMemoryMaintenanceTicketRepository]:
    ticket_repository = InMemoryMaintenanceTicketRepository()
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(llm_client, profile),
        ProductHistoryCapability(EmptyProductHistoryRepository()),
        MachineStatusCapability(EmptyMachineStatusRepository()),
        MaintenanceTicketCapability(ticket_repository),
        checkpointer=checkpointer,
        run_classification=classification,
    )
    return agent, ticket_repository


def test_action_request_interrupts_and_checkpoint_keeps_structured_payload() -> None:
    agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(action_response()),
        checkpointer=InMemorySaver(),
    )

    state = agent.start("Create a maintenance ticket for S04.", thread_id="ticket-1")
    payload = agent.get_interrupt_payload(thread_id="ticket-1")

    assert state["pending_action"] is not None
    assert state["approval_result"] is None
    assert ticket_repository.tickets == ()
    assert payload == {
        "kind": "action_approval",
        "action": CREATE_MAINTENANCE_TICKET_TOOL_NAME,
        "details": {"station_id": "S04", "summary": "Investigate E-STOP-17"},
    }
    json.dumps(payload)


def test_thread_ids_isolate_paused_runs() -> None:
    agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(
            action_response(station_id="S04", call_id="ticket-a"),
            action_response(station_id="S12", call_id="ticket-b"),
        ),
        checkpointer=InMemorySaver(),
    )

    agent.start("Create a ticket for S04.", thread_id="thread-a")
    agent.start("Create a ticket for S12.", thread_id="thread-b")

    assert agent.get_interrupt_payload(thread_id="thread-a") == {
        "kind": "action_approval",
        "action": CREATE_MAINTENANCE_TICKET_TOOL_NAME,
        "details": {"station_id": "S04", "summary": "Investigate E-STOP-17"},
    }
    assert agent.get_interrupt_payload(thread_id="thread-b") == {
        "kind": "action_approval",
        "action": CREATE_MAINTENANCE_TICKET_TOOL_NAME,
        "details": {"station_id": "S12", "summary": "Investigate E-STOP-17"},
    }
    assert ticket_repository.tickets == ()


def test_approved_resume_executes_action_once_and_terminates() -> None:
    agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(action_response(), final_response("Ticket created.")),
        checkpointer=InMemorySaver(),
    )

    agent.start("Create a maintenance ticket for S04.", thread_id="approve-thread")
    state = agent.resume(thread_id="approve-thread", approval="approve")

    assert state["run_status"] is AgentRunStatus.SUCCESS
    assert state["final_answer"] == "Ticket created."
    assert state["executed_tool_count"] == 1
    assert state["executed_tool_calls"][0].tool == CREATE_MAINTENANCE_TICKET_TOOL_NAME
    assert len(ticket_repository.tickets) == 1
    assert agent.get_interrupt_payload(thread_id="approve-thread") is None
    repeated_state = agent.resume(thread_id="approve-thread", approval="approve")
    assert repeated_state["run_status"] is AgentRunStatus.SUCCESS
    assert len(ticket_repository.tickets) == 1


def test_checkpoint_state_uses_serializer_safe_primitives() -> None:
    checkpointer = InMemorySaver()
    agent, _ = create_hitl_agent(
        FakeLLMClient(action_response(), final_response("Ticket created.")),
        checkpointer=checkpointer,
    )

    agent.start("Create a maintenance ticket for S04.", thread_id="primitive-thread")
    snapshot = agent._graph.get_state(
        {"configurable": {"thread_id": "primitive-thread"}}
    )

    assert snapshot.values["run_status"] is None
    assert snapshot.values["approval_result"] is None
    assert snapshot.values["run_classification"] == int(DataClassification.CONFIDENTIAL)
    assert snapshot.values["executed_tool_calls"] == []


def test_rejected_resume_never_executes_action_and_terminates_cleanly() -> None:
    agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(action_response()),
        checkpointer=InMemorySaver(),
    )

    agent.start("Create a maintenance ticket for S04.", thread_id="reject-thread")
    state = agent.resume(thread_id="reject-thread", approval="reject")

    assert state["run_status"] is AgentRunStatus.SUCCESS
    assert state["final_answer"] == (
        "Maintenance ticket creation was rejected; no ticket was created."
    )
    assert state["executed_tool_count"] == 0
    assert ticket_repository.tickets == ()


def test_invalid_resume_value_fails_without_executing_action() -> None:
    agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(action_response()),
        checkpointer=InMemorySaver(),
    )

    agent.start("Create a maintenance ticket for S04.", thread_id="invalid-thread")

    with pytest.raises(ValueError, match="Approval must be either"):
        agent.resume(thread_id="invalid-thread", approval="later")

    assert ticket_repository.tickets == ()


def test_same_thread_can_continue_only_with_matching_profile_and_classification() -> (
    None
):
    checkpointer = InMemorySaver()
    original_agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(action_response(), final_response()),
        checkpointer=checkpointer,
        profile=ModelProfile("local_quality"),
        classification=DataClassification.CONFIDENTIAL,
    )
    original_agent.start(
        "Create a maintenance ticket for S04.", thread_id="secure-thread"
    )
    mismatched_agent, _ = create_hitl_agent(
        FakeLLMClient(final_response()),
        checkpointer=checkpointer,
        profile=ModelProfile("public_fast"),
        classification=DataClassification.PUBLIC,
    )

    with pytest.raises(RuntimeError, match="model profile does not match"):
        mismatched_agent.resume(thread_id="secure-thread", approval="approve")

    assert ticket_repository.tickets == ()
    state = original_agent.resume(thread_id="secure-thread", approval="approve")
    assert state["run_status"] is AgentRunStatus.SUCCESS
    assert len(ticket_repository.tickets) == 1


def test_resume_rejects_a_changed_data_classification() -> None:
    checkpointer = InMemorySaver()
    original_agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(action_response()),
        checkpointer=checkpointer,
        classification=DataClassification.CONFIDENTIAL,
    )
    original_agent.start(
        "Create a maintenance ticket for S04.", thread_id="class-thread"
    )
    mismatched_agent, _ = create_hitl_agent(
        FakeLLMClient(final_response()),
        checkpointer=checkpointer,
        classification=DataClassification.PUBLIC,
    )

    with pytest.raises(RuntimeError, match="data classification does not match"):
        mismatched_agent.resume(thread_id="class-thread", approval="approve")

    assert ticket_repository.tickets == ()


def test_confidential_checkpointed_run_is_blocked_before_public_adapter_call() -> None:
    adapter = FakeLLMClient(action_response())
    checked_client = EgressCheckedLLMClient(
        adapter,
        StaticExecutionZoneResolver(ExecutionZone.PUBLIC_CLOUD),
        DataClassification.CONFIDENTIAL,
    )
    ticket_repository = InMemoryMaintenanceTicketRepository()
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(checked_client, ModelProfile("public_fast")),
        ProductHistoryCapability(EmptyProductHistoryRepository()),
        MachineStatusCapability(EmptyMachineStatusRepository()),
        MaintenanceTicketCapability(ticket_repository),
        checkpointer=InMemorySaver(),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    with pytest.raises(ModelEgressDeniedError, match="Model egress denied by policy"):
        agent.start("Create a maintenance ticket for S04.", thread_id="public-thread")

    assert adapter.requests == []
    assert ticket_repository.tickets == ()


def test_read_only_run_with_checkpoint_never_interrupts() -> None:
    agent, ticket_repository = create_hitl_agent(
        FakeLLMClient(product_history_response(), final_response()),
        checkpointer=InMemorySaver(),
    )

    state = agent.start(
        "Show the production history for P4711.", thread_id="read-thread"
    )

    assert state["run_status"] is AgentRunStatus.SUCCESS
    assert state["executed_tool_count"] == 1
    assert agent.get_interrupt_payload(thread_id="read-thread") is None
    assert ticket_repository.tickets == ()


def test_ticket_repository_is_idempotent_for_the_same_request_id() -> None:
    repository = InMemoryMaintenanceTicketRepository()
    capability = MaintenanceTicketCapability(repository)

    first_result = capability.create_maintenance_ticket(
        request_id="tool-call-1",
        station_id="S04",
        summary="Investigate E-STOP-17",
    )
    second_result = capability.create_maintenance_ticket(
        request_id="tool-call-1",
        station_id="S04",
        summary="Investigate E-STOP-17",
    )

    assert first_result == second_result
    assert len(repository.tickets) == 1
