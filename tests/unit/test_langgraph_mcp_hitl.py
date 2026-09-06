from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

import pytest
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from industrial_ai_agent.agent.agent_run import (
    AgentRunStatus,
    InvalidToolArgumentsError,
)
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    CREATE_MAINTENANCE_TICKET_TOOL_NAME,
    MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
    LangGraphTroubleshootingAgent,
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
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.tools.tool_contracts import (
    CreateMaintenanceTicketExecutionArguments,
)

DEFAULT_PROFILE = ModelProfile("local_quality")


def test_system_message_requires_compact_investigation_markdown_tables() -> None:
    message = MCP_TROUBLESHOOTING_SYSTEM_MESSAGE

    assert "`| Step | Action | Findings / Notes |`" in message
    assert "exactly one physical Markdown line" in message
    assert "separate multiple items in the same cell with `<br>`" in message
    assert "continuation rows with an empty Step or Action cell" in message
    assert "below the table instead" in message
    assert "`### Investigation Summary`" in message
    assert "`### Likely Root Cause`" in message
    assert "`### Recommended Investigation Actions`" in message
    assert "`### Next Steps`" in message
    assert "distinguish collected evidence from inference" in message
    assert "Keep `### Next Steps` concise and actionable" in message
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


def _agent(
    client: FakeLLMClient,
    provider: RecordingMcpToolProvider,
    checkpointer: InMemorySaver,
    *,
    profile: ModelProfile = DEFAULT_PROFILE,
    classification: DataClassification = DataClassification.CONFIDENTIAL,
) -> LangGraphTroubleshootingAgent:
    return LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, profile),
        mcp_tool_provider=cast(McpToolProvider, cast(object, provider)),
        checkpointer=checkpointer,
        run_classification=classification,
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
