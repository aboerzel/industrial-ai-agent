from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast
from uuid import uuid4

import pytest
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from industrial_ai_agent.agent.agent_run import (
    AgentRunStatus,
    InvalidToolArgumentsError,
)
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    CREATE_MAINTENANCE_TICKET_TOOL_NAME,
    EXECUTE_REFERENCE_CALIBRATION_TOOL_NAME,
    MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
    LangGraphTroubleshootingAgent,
    _model_visible_tools,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.agent.mcp_tool_provider import McpToolProvider, McpToolSession
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.agent.troubleshooting_run_service import ConversationTurn
from industrial_ai_agent.domain.closed_loop_recovery import RecoveryOutcome
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.tools.tool_contracts import (
    CreateMaintenanceTicketExecutionArguments,
)

DEFAULT_PROFILE = ModelProfile("local_quality")


def test_system_message_requires_structured_investigation_steps() -> None:
    message = MCP_TROUBLESHOOTING_SYSTEM_MESSAGE

    assert "`investigation_steps`" in message
    assert "exact step number and canonical tool name" in message
    assert "Never invent, " in message
    assert "executed-tool Markdown table" in message
    assert "Untersuchungsübersicht" in message
    assert "`### Likely Root Cause`" in message
    assert "`answer` Markdown string, a bounded `investigation_steps` list" in message
    assert "follow-up prompts exclusively in `next_steps`" in message
    assert "Put ALL concrete" in message
    assert "`Recommended Actions`" in message
    assert "`Nächste Schritte`" in message
    assert "distinguish collected evidence from inference" in message
    assert "Keep the answer concise and evidence-based" in message
    assert "or explicit factory-discovery request, do not call a tool" in message


@dataclass
class FakeLLMClient:
    responses: list[LLMResponse]
    requests: list[LLMRequest] = field(default_factory=list)

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        del profile
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected LLM call")
        return self.responses.pop(0)


@dataclass
class RecordingMcpToolProvider:
    calls: list[dict[str, str]] = field(default_factory=list)

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        async def create_maintenance_ticket(
            station_id: str, summary: str, request_id: str
        ) -> str:
            self.calls.append(
                {
                    "station_id": station_id,
                    "summary": summary,
                    "request_id": request_id,
                }
            )
            return json.dumps({"ticket_id": "MT-1", "classification": "CONFIDENTIAL"})

        yield McpToolSession(
            tools=(
                StructuredTool.from_function(
                    coroutine=create_maintenance_ticket,
                    name=CREATE_MAINTENANCE_TICKET_TOOL_NAME,
                    description="Create a maintenance ticket.",
                    args_schema=CreateMaintenanceTicketExecutionArguments,
                ),
            ),
            discovered_tool_names=(CREATE_MAINTENANCE_TICKET_TOOL_NAME,),
            server_name="fake_factory_mcp",
            server_version="test",
            protocol_version="test",
            tool_policies=(
                ToolPolicy(
                    CREATE_MAINTENANCE_TICKET_TOOL_NAME,
                    ToolOperation.WRITE,
                    requires_approval=True,
                ),
            ),
        )


@dataclass
class HardwareRecoveryMcpToolProvider:
    calls: list[dict[str, str]] = field(default_factory=list)
    status_result: str = (
        '{"station_id":"S04","device_id":"POSITION-ENC-02",'
        '"reference_valid":false,"position_deviation_mm":0.43,'
        '"configured_tolerance_mm":0.20,"calibration_supported":true,'
        '"classification":"CONFIDENTIAL"}'
    )
    preparation_result: str = (
        '{"station_id":"S04","device_id":"POSITION-ENC-02",'
        '"proposed_operation":"reference_calibration",'
        '"requires_approval":true,"precondition_evaluations":['
        '{"status":"PASSED"},{"status":"PASSED"},'
        '{"status":"PASSED"},{"status":"PASSED"}],'
        '"classification":"CONFIDENTIAL"}'
    )
    execution_result: str = (
        '{"action_executed":true,"verification_status":"PASSED",'
        '"recovery_outcome":"SUCCEEDED","classification":"CONFIDENTIAL"}'
    )

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        async def get_position_reference_status(station_id: str) -> str:
            assert station_id == "S04"
            return self.status_result

        async def prepare_reference_calibration(station_id: str) -> str:
            assert station_id == "S04"
            return self.preparation_result

        async def execute_reference_calibration(
            station_id: str,
            device_id: str,
            run_id: str,
            action_id: str,
        ) -> str:
            self.calls.append(
                {
                    "station_id": station_id,
                    "device_id": device_id,
                    "run_id": run_id,
                    "action_id": action_id,
                }
            )
            return self.execution_result

        yield McpToolSession(
            tools=(
                StructuredTool.from_function(
                    coroutine=get_position_reference_status,
                    name="get_position_reference_status",
                    description="Get bounded position-reference status.",
                ),
                StructuredTool.from_function(
                    coroutine=prepare_reference_calibration,
                    name="prepare_reference_calibration",
                    description="Prepare reference calibration.",
                ),
                StructuredTool.from_function(
                    coroutine=execute_reference_calibration,
                    name=EXECUTE_REFERENCE_CALIBRATION_TOOL_NAME,
                    description="Execute server-approved reference calibration.",
                ),
            ),
            discovered_tool_names=(
                "get_position_reference_status",
                "prepare_reference_calibration",
                EXECUTE_REFERENCE_CALIBRATION_TOOL_NAME,
            ),
            server_name="fake_hardware_mcp",
            server_version="test",
            protocol_version="test",
            tool_policies=(
                ToolPolicy("get_position_reference_status", ToolOperation.READ),
                ToolPolicy("prepare_reference_calibration", ToolOperation.READ),
                ToolPolicy(
                    EXECUTE_REFERENCE_CALIBRATION_TOOL_NAME,
                    ToolOperation.WRITE,
                    requires_approval=True,
                ),
            ),
        )


def test_model_visible_hardware_recovery_tools_are_station_oriented() -> None:
    provider = HardwareRecoveryMcpToolProvider()

    async def visible_schemas() -> dict[str, set[str]]:
        async with provider.open_session() as session:
            visible_tools = _model_visible_tools(session.tools, session.tool_policies)
            return {
                tool.name: set(tool.args_schema.model_json_schema()["properties"])
                for tool in visible_tools
            }

    schemas = asyncio.run(visible_schemas())

    assert schemas == {
        "get_position_reference_status": {"station_id"},
        "prepare_reference_calibration": {"station_id"},
        "execute_reference_calibration": {"station_id"},
    }


@dataclass
class ReadRecordingMcpToolProvider:
    tool_results: tuple[str, str]

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        async def get_product_history(product_id: str) -> str:
            assert product_id == "P4711"
            return self.tool_results[0]

        async def search_documentation(query: str, top_k: int) -> str:
            assert query == "QUALITY-09"
            assert top_k == 1
            return self.tool_results[1]

        yield McpToolSession(
            tools=(
                StructuredTool.from_function(
                    coroutine=get_product_history,
                    name="get_product_history",
                    description="Get product history.",
                ),
                StructuredTool.from_function(
                    coroutine=search_documentation,
                    name="search_documentation",
                    description="Search documentation.",
                ),
            ),
            discovered_tool_names=("get_product_history", "search_documentation"),
            server_name="fake_read_mcp",
            server_version="test",
            protocol_version="test",
            tool_policies=(
                ToolPolicy("get_product_history", ToolOperation.READ),
                ToolPolicy("search_documentation", ToolOperation.READ),
            ),
        )


def _action_response(
    arguments: dict[str, object] | None = None,
) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(
            LLMToolCall(
                id="ticket-call-1",
                name=CREATE_MAINTENANCE_TICKET_TOOL_NAME,
                arguments=arguments
                or {"station_id": "S04", "summary": "Investigate E-STOP-17"},
            ),
        ),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def _final_response() -> LLMResponse:
    return LLMResponse(text="Ticket created.", finish_reason=FinishReason.STOP)


def _reference_calibration_action_response() -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(
            LLMToolCall(
                id="reference-calibration-call-1",
                name=EXECUTE_REFERENCE_CALIBRATION_TOOL_NAME,
                arguments={"station_id": "S04"},
            ),
        ),
        finish_reason=FinishReason.TOOL_CALLS,
    )


@pytest.mark.parametrize(
    ("user_message", "tool_results", "final_answer", "response_language"),
    (
        (
            (
                "Untersuche, warum Produkt P4711 an Station S04 fehlgeschlagen ist. "
                "Verwende bei Bedarf die vorhandene Dokumentation."
            ),
            (
                '{"classification":"CONFIDENTIAL","finding":"QUALITY-09 failed"}',
                '{"classification":"CONFIDENTIAL","content":"English maintenance guidance"}',
            ),
            "P4711 ist an S04 mit QUALITY-09 fehlgeschlagen.",
            ResponseLanguage.DE,
        ),
        (
            (
                "Investigate why product P4711 failed at station S04. "
                "Use the available documentation if needed."
            ),
            (
                '{"classification":"CONFIDENTIAL","finding":"QUALITÄT-09 fehlgeschlagen"}',
                '{"classification":"CONFIDENTIAL","content":"Deutsche Wartungshinweise"}',
            ),
            "P4711 failed at S04 with QUALITY-09.",
            ResponseLanguage.EN,
        ),
    ),
)
def test_multi_tool_loops_keep_the_run_response_language(
    user_message: str,
    tool_results: tuple[str, str],
    final_answer: str,
    response_language: ResponseLanguage,
) -> None:
    client = FakeLLMClient(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="history",
                        name="get_product_history",
                        arguments={"product_id": "P4711"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="documentation",
                        name="search_documentation",
                        arguments={"query": "QUALITY-09", "top_k": 1},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(
                text=json.dumps(
                    {
                        "answer": final_answer,
                        "next_steps": [
                            (
                                "Prüfe den aktuellen Zustand von Station S04."
                                if response_language is ResponseLanguage.DE
                                else "Check the current status of station S04."
                            )
                        ],
                    }
                ),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, DEFAULT_PROFILE),
        mcp_tool_provider=cast(
            McpToolProvider,
            cast(object, ReadRecordingMcpToolProvider(tool_results)),
        ),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    state = asyncio.run(agent.ainvoke_via_mcp(user_message))

    assert state["response_language"] is response_language
    assert state["final_answer"] == final_answer
    assert state["next_steps"] == (
        (
            "Prüfe den aktuellen Zustand von Station S04."
            if response_language is ResponseLanguage.DE
            else "Check the current status of station S04."
        ),
    )
    assert len(client.requests) == 3
    for llm_request in client.requests:
        assert llm_request.messages[0].content is not None
        assert f"Response language: {response_language.display_name}." in (
            llm_request.messages[0].content or ""
        )
    assert any(
        tool_result in (client.requests[-1].messages[-1].content or "")
        for tool_result in tool_results
    )


def test_hitl_resume_keeps_the_original_response_language() -> None:
    checkpointer = InMemorySaver()
    provider = RecordingMcpToolProvider()
    started, _ = asyncio.run(
        _agent(
            FakeLLMClient([_action_response()]), provider, checkpointer
        ).astart_via_mcp(
            "Erstelle ein Wartungsticket für S04.",
            thread_id="language-resume-1",
        )
    )
    resumed_client = FakeLLMClient(
        [
            LLMResponse(
                text="Das Wartungsticket wurde erstellt.",
                finish_reason=FinishReason.STOP,
            )
        ]
    )

    completed = asyncio.run(
        _agent(resumed_client, provider, checkpointer).aresume_via_mcp(
            thread_id="language-resume-1", approval="approve"
        )
    )

    assert started["response_language"] is ResponseLanguage.DE
    assert completed["response_language"] is ResponseLanguage.DE
    assert completed["final_answer"] == "Das Wartungsticket wurde erstellt."
    assert "Response language: German." in (
        resumed_client.requests[0].messages[0].content or ""
    )


def test_follow_up_context_is_bounded_and_labels_prior_user_claims_as_untrusted() -> (
    None
):
    client = FakeLLMClient(
        [LLMResponse(text="Follow-up answer.", finish_reason=FinishReason.STOP)]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, DEFAULT_PROFILE),
        mcp_tool_provider=cast(
            McpToolProvider,
            cast(object, ReadRecordingMcpToolProvider(("{}", "{}"))),
        ),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(
        agent.aanswer_via_mcp(
            "Check point 1 and 3.",
            conversation_context=(
                ConversationTurn(
                    user_request="I think firmware was updated yesterday.",
                    agent_answer="1. Inspect station status.\n2. Review documentation.\n3. Verify alarms.",
                ),
            ),
        )
    )

    assert result.final_answer == "Follow-up answer."
    context = client.requests[0].messages[1].content or ""
    assert "USER PROVIDED:" in context
    assert "not independently verified" in context
    assert "firmware was updated yesterday" in context


def _agent(
    client: FakeLLMClient,
    provider: RecordingMcpToolProvider,
    checkpointer: InMemorySaver,
    *,
    profile: ModelProfile = DEFAULT_PROFILE,
    classification: DataClassification = DataClassification.CONFIDENTIAL,
    requires_verified_recovery: bool = False,
) -> LangGraphTroubleshootingAgent:
    return LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, profile),
        mcp_tool_provider=cast(McpToolProvider, cast(object, provider)),
        checkpointer=checkpointer,
        run_classification=classification,
        requires_verified_recovery=requires_verified_recovery,
    )


def test_mcp_hitl_interrupt_approves_once_and_survives_agent_recreation() -> None:
    checkpointer = InMemorySaver()
    provider = RecordingMcpToolProvider()
    started, payload = asyncio.run(
        _agent(
            FakeLLMClient([_action_response()]), provider, checkpointer
        ).astart_via_mcp("Create a maintenance ticket for S04.", thread_id="ticket-1")
    )

    assert started["pending_action"] is not None
    assert started["model_profile_name"] == "local_quality"
    assert started["run_classification"] is DataClassification.CONFIDENTIAL
    assert payload == {
        "kind": "action_approval",
        "action": CREATE_MAINTENANCE_TICKET_TOOL_NAME,
        "details": {"station_id": "S04", "summary": "Investigate E-STOP-17"},
    }
    assert provider.calls == []

    recreated = _agent(FakeLLMClient([_final_response()]), provider, checkpointer)
    completed = asyncio.run(
        recreated.aresume_via_mcp(thread_id="ticket-1", approval="approve")
    )
    repeated = asyncio.run(
        recreated.aresume_via_mcp(thread_id="ticket-1", approval="approve")
    )

    assert completed["run_status"] is AgentRunStatus.SUCCESS
    assert repeated["run_status"] is AgentRunStatus.SUCCESS
    assert completed["executed_tool_count"] == 1
    assert len(provider.calls) == 1
    assert provider.calls[0]["request_id"] == "ticket-call-1"


def test_mcp_hitl_reject_never_executes_write() -> None:
    checkpointer = InMemorySaver()
    provider = RecordingMcpToolProvider()
    agent = _agent(FakeLLMClient([_action_response()]), provider, checkpointer)
    asyncio.run(agent.astart_via_mcp("Create a ticket.", thread_id="reject-1"))

    rejected = asyncio.run(
        agent.aresume_via_mcp(thread_id="reject-1", approval="reject")
    )

    assert rejected["run_status"] is AgentRunStatus.SUCCESS
    assert rejected["pending_action"] is None
    assert provider.calls == []


def test_hardware_recovery_hitl_binds_approved_execution_to_run_and_keeps_budget() -> (
    None
):
    checkpointer = InMemorySaver()
    provider = HardwareRecoveryMcpToolProvider()
    run_id = str(uuid4())
    start_client = FakeLLMClient(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="status-call-1",
                        name="get_position_reference_status",
                        arguments={"station_id": "S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(start_client, DEFAULT_PROFILE),
        mcp_tool_provider=cast(McpToolProvider, cast(object, provider)),
        checkpointer=checkpointer,
        run_classification=DataClassification.CONFIDENTIAL,
        requires_verified_recovery=True,
    )

    started, payload = asyncio.run(
        agent.astart_via_mcp("Recover S04 position reference.", thread_id=run_id)
    )

    assert started["executed_tool_count"] == 2
    assert started["run_status"] is None
    assert payload is not None
    assert payload["kind"] == "action_approval"
    assert payload["action"] == EXECUTE_REFERENCE_CALIBRATION_TOOL_NAME
    assert isinstance(payload["action_id"], str)
    assert payload["details"] == {
        "station_id": "S04",
        "device_id": "POSITION-ENC-02",
        "operation_type": "reference_calibration",
        "summary": "Run controlled reference calibration for POSITION-ENC-02 at S04.",
    }
    assert provider.calls == []

    resumed_agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(FakeLLMClient([]), DEFAULT_PROFILE),
        mcp_tool_provider=cast(McpToolProvider, cast(object, provider)),
        checkpointer=checkpointer,
        run_classification=DataClassification.CONFIDENTIAL,
        requires_verified_recovery=True,
    )
    completed = asyncio.run(
        resumed_agent.aresume_via_mcp(thread_id=run_id, approval="approve")
    )
    repeated = asyncio.run(
        resumed_agent.aresume_via_mcp(thread_id=run_id, approval="approve")
    )

    assert completed["executed_tool_count"] == 3
    assert repeated["executed_tool_count"] == 3
    assert completed["run_status"] is AgentRunStatus.SUCCESS
    assert provider.calls == [
        {
            "station_id": "S04",
            "device_id": "POSITION-ENC-02",
            "run_id": run_id,
            "action_id": payload["action_id"],
        }
    ]


def test_hardware_recovery_hitl_rejection_never_calls_execution_tool() -> None:
    checkpointer = InMemorySaver()
    provider = HardwareRecoveryMcpToolProvider()
    run_id = str(uuid4())
    client = FakeLLMClient(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="status-call-1",
                        name="get_position_reference_status",
                        arguments={"station_id": "S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, DEFAULT_PROFILE),
        mcp_tool_provider=cast(McpToolProvider, cast(object, provider)),
        checkpointer=checkpointer,
        run_classification=DataClassification.CONFIDENTIAL,
        requires_verified_recovery=True,
    )
    asyncio.run(
        agent.astart_via_mcp("Recover S04 position reference.", thread_id=run_id)
    )

    rejected = asyncio.run(agent.aresume_via_mcp(thread_id=run_id, approval="reject"))

    assert rejected["executed_tool_count"] == 2
    assert rejected["run_status"] is AgentRunStatus.RECOVERY_BLOCKED
    assert provider.calls == []


def test_recovery_intent_bypasses_premature_text_after_recoverable_status() -> None:
    checkpointer = InMemorySaver()
    provider = HardwareRecoveryMcpToolProvider()
    client = FakeLLMClient(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="status-call-1",
                        name="get_position_reference_status",
                        arguments={"station_id": "S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(
                text="Reference calibration should be prepared.",
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    agent = _agent(
        client,
        provider,
        checkpointer,
        requires_verified_recovery=True,
    )

    state, payload = asyncio.run(
        agent.astart_via_mcp("Recover S04 position reference.", thread_id="early-stop")
    )

    assert payload is not None
    assert state["run_status"] is None
    assert state["executed_tool_count"] == 2
    assert [call.tool for call in state["executed_tool_calls"]] == [
        "get_position_reference_status",
        "prepare_reference_calibration",
    ]
    assert len(client.requests) == 1
    assert provider.calls == []


def test_healthy_recovery_status_terminates_as_trusted_no_op() -> None:
    checkpointer = InMemorySaver()
    provider = HardwareRecoveryMcpToolProvider(
        status_result=(
            '{"station_id":"S04","device_id":"POSITION-ENC-02",'
            '"reference_valid":true,"position_deviation_mm":0.08,'
            '"configured_tolerance_mm":0.20,"calibration_supported":true,'
            '"classification":"CONFIDENTIAL"}'
        )
    )
    client = FakeLLMClient(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="status-call-1",
                        name="get_position_reference_status",
                        arguments={"station_id": "S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
        ]
    )

    state, payload = asyncio.run(
        _agent(
            client,
            provider,
            checkpointer,
            requires_verified_recovery=True,
        ).astart_via_mcp("Recover S04 position reference.", thread_id="healthy-s04")
    )

    assert state["run_status"] is AgentRunStatus.SUCCESS
    assert state["recovery_outcome"] is RecoveryOutcome.NOT_REQUIRED
    assert state["executed_tool_count"] == 1
    assert [call.tool for call in state["executed_tool_calls"]] == [
        "get_position_reference_status"
    ]
    assert state["final_answer"] == (
        "No recovery is required. The position reference at station S04 is already valid."
    )
    assert payload is None
    assert provider.calls == []
    assert len(client.requests) == 1


def test_recovery_preparation_block_skips_hitl_and_execution() -> None:
    checkpointer = InMemorySaver()
    provider = HardwareRecoveryMcpToolProvider(
        preparation_result=(
            '{"station_id":"S04","device_id":"POSITION-ENC-02",'
            '"proposed_operation":"reference_calibration",'
            '"requires_approval":true,"precondition_evaluations":['
            '{"status":"FAILED"}],"classification":"CONFIDENTIAL"}'
        )
    )
    client = FakeLLMClient(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="status-call-1",
                        name="get_position_reference_status",
                        arguments={"station_id": "S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
        ]
    )
    agent = _agent(
        client,
        provider,
        checkpointer,
        requires_verified_recovery=True,
    )

    state, payload = asyncio.run(
        agent.astart_via_mcp("Recover S04 position reference.", thread_id="blocked")
    )

    assert payload is None
    assert state["run_status"] is AgentRunStatus.RECOVERY_BLOCKED
    assert state["executed_tool_count"] == 2
    assert [call.tool for call in state["executed_tool_calls"]] == [
        "get_position_reference_status",
        "prepare_reference_calibration",
    ]
    assert len(client.requests) == 1
    assert provider.calls == []


@pytest.mark.parametrize(
    ("execution_result", "expected_status"),
    (
        (
            (
                '{"action_executed":false,"verification_status":"NOT_RUN",'
                '"recovery_outcome":"BLOCKED","classification":"CONFIDENTIAL"}'
            ),
            AgentRunStatus.RECOVERY_BLOCKED,
        ),
        (
            (
                '{"action_executed":true,"verification_status":"FAILED",'
                '"recovery_outcome":"FAILED","classification":"CONFIDENTIAL"}'
            ),
            AgentRunStatus.RECOVERY_FAILED,
        ),
    ),
)
def test_recovery_execution_non_success_never_becomes_completed(
    execution_result: str, expected_status: AgentRunStatus
) -> None:
    checkpointer = InMemorySaver()
    provider = HardwareRecoveryMcpToolProvider(execution_result=execution_result)
    run_id = str(uuid4())
    agent = _agent(
        FakeLLMClient(
            [
                LLMResponse(
                    text=None,
                    tool_calls=(
                        LLMToolCall(
                            id="status-call-1",
                            name="get_position_reference_status",
                            arguments={"station_id": "S04"},
                        ),
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ]
        ),
        provider,
        checkpointer,
        requires_verified_recovery=True,
    )
    asyncio.run(
        agent.astart_via_mcp("Recover S04 position reference.", thread_id=run_id)
    )

    completed = asyncio.run(
        _agent(
            FakeLLMClient([]),
            provider,
            checkpointer,
            requires_verified_recovery=True,
        ).aresume_via_mcp(thread_id=run_id, approval="approve")
    )

    assert completed["run_status"] is expected_status
    assert completed["executed_tool_count"] == 3
    assert len(provider.calls) == 1


def test_mcp_hitl_rejects_model_controlled_idempotency_key_before_write() -> None:
    provider = RecordingMcpToolProvider()
    agent = _agent(
        FakeLLMClient(
            [
                _action_response(
                    {
                        "station_id": "S04",
                        "summary": "Investigate E-STOP-17",
                        "request_id": "model-controlled",
                    }
                )
            ]
        ),
        provider,
        InMemorySaver(),
    )

    with pytest.raises(InvalidToolArgumentsError, match="Invalid arguments"):
        asyncio.run(agent.astart_via_mcp("Create a ticket.", thread_id="invalid-1"))

    assert provider.calls == []


def test_mcp_hitl_resume_fails_closed_for_changed_profile_or_classification() -> None:
    checkpointer = InMemorySaver()
    provider = RecordingMcpToolProvider()
    asyncio.run(
        _agent(
            FakeLLMClient([_action_response()]), provider, checkpointer
        ).astart_via_mcp("Create a ticket.", thread_id="secure-1")
    )

    wrong_profile = _agent(
        FakeLLMClient([_final_response()]),
        provider,
        checkpointer,
        profile=ModelProfile("public_fast"),
    )
    with pytest.raises(RuntimeError, match="model profile does not match"):
        asyncio.run(
            wrong_profile.aresume_via_mcp(thread_id="secure-1", approval="approve")
        )

    wrong_classification = _agent(
        FakeLLMClient([_final_response()]),
        provider,
        checkpointer,
        classification=DataClassification.PUBLIC,
    )
    with pytest.raises(RuntimeError, match="data classification does not match"):
        asyncio.run(
            wrong_classification.aresume_via_mcp(
                thread_id="secure-1", approval="approve"
            )
        )

    assert provider.calls == []
