"""Deterministic regressions for the post-refactoring stabilization boundaries."""

import asyncio
from dataclasses import replace
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from openai import APIStatusError, OpenAI
from test_fastapi_api import FakeRunService, _success_result, create_app
from test_langgraph_mcp_hitl import (
    FakeLLMClient,
    HardwareRecoveryMcpToolProvider,
    _agent,
)
from test_openai_compatible_llm_client import create_configuration
from test_rca_mcp_server import RUN_ID, _FakeAnalysisService
from test_runtime_mcp_server import _FakeRuntimeStore, _inspection, _server

from industrial_ai_agent.agent.agent_run import MAX_TOOL_CALLS, AgentRunStatus
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    MessageRole,
    ModelId,
)
from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.application.rca_reasoning import (
    RcaReasoningResult,
    RcaReasoningStatus,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.postgres_run_store import _safe_tool_names
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    create_default_factory_mcp_server,
)
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.persistence.postgres import _safe_media_type
from industrial_ai_agent.infrastructure.rca_mcp_server import create_rca_mcp_server
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability


def test_local_model_redirect_cannot_forward_request_body():
    seen = []

    def transport(request):
        seen.append(str(request.url))
        return httpx.Response(
            307, headers={"location": "https://sink.invalid/v1/chat/completions"}
        )

    def factory(**kwargs):
        client = kwargs["http_client"]
        assert not client.follow_redirects
        assert not client.trust_env
        client.close()
        kwargs["http_client"] = httpx.Client(
            transport=httpx.MockTransport(transport),
            trust_env=False,
            follow_redirects=False,
        )
        return OpenAI(**kwargs)

    adapter = OpenAICompatibleLLMClient(
        create_configuration(), environment={}, client_factory=factory
    )
    try:
        with pytest.raises(APIStatusError, match="307"):
            adapter.chat(
                ModelId("local_quality"),
                LLMRequest(
                    messages=(LLMMessage(role=MessageRole.USER, content="SYNTHETIC"),)
                ),
            )
        assert seen == ["http://localhost:11434/v1/chat/completions"]
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://remote.invalid/v1",
        "http://127.0.0.1.evil.invalid/v1",
        "http://user:password@localhost:11434/v1",
    ],
)
def test_effective_local_destination_is_checked_before_sdk_creation(endpoint):
    configuration = create_configuration()
    configuration = configuration.model_copy(
        update={
            "models": (
                configuration.models[0].model_copy(
                    update={"base_url_env": "TEST_MODEL_URL"}
                ),
            )
        }
    )

    def forbidden(**kwargs):
        pytest.fail("Invalid destination reached the SDK")

    adapter = OpenAICompatibleLLMClient(
        configuration,
        environment={"TEST_MODEL_URL": endpoint},
        client_factory=forbidden,
    )
    with pytest.raises((PermissionError, ValueError)):
        adapter.chat(ModelId("local_quality"), LLMRequest(messages=()))


@pytest.mark.parametrize(
    "mime",
    ["text/html", "image/svg+xml", "application/xhtml+xml", "application/javascript"],
)
def test_active_document_formats_are_not_executable_media(mime):
    assert _safe_media_type(mime) == "application/octet-stream"


def test_unknown_or_hidden_investigation_cannot_be_appended_with_public_scaffold():
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))
    hidden = client.post(
        "/api/v1/runs",
        json={"message": "Investigate P4711.", "user_clearance": "CONFIDENTIAL"},
    ).json()["investigation_id"]
    before = len(service.messages)
    for investigation_id in (hidden, str(uuid4())):
        response = client.post(
            "/api/v1/runs",
            json={
                "message": "Investigate S01.",
                "user_clearance": "PUBLIC",
                "investigation_id": investigation_id,
            },
        )
        assert response.status_code == 404
        assert response.json()["code"] == "requested_data_unavailable"
    assert len(service.messages) == before


def test_ticket_idempotency_is_scoped_to_the_approved_run():
    class Claims:
        async def claim_approved_action(self, claim, context):
            assert claim.action_id == "same-model-id"
            return True

    repository = InMemoryMaintenanceTicketRepository()
    capability = MaintenanceTicketCapability(repository, approval_claims=Claims())
    context = SecurityContext(
        "synthetic", ("test",), DataClassification.CONFIDENTIAL, True
    )

    async def verify():
        first = await capability.create_maintenance_ticket(
            "same-model-id", "S04", "First", run_id=uuid4(), security_context=context
        )
        second = await capability.create_maintenance_ticket(
            "same-model-id", "S02", "Second", run_id=uuid4(), security_context=context
        )
        assert first.ticket_id != second.ticket_id
        assert second.station_id == "S02"
        assert second.summary == "Second"

    asyncio.run(verify())


def test_postgres_stdio_composition_retains_authoritative_approval_port(monkeypatch):
    monkeypatch.setenv(
        "FACTORY_DATABASE_URL",
        "postgresql+psycopg://synthetic:synthetic@127.0.0.1:5432/synthetic",
    )
    server = create_default_factory_mcp_server()
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {"get_machine_status", "create_maintenance_ticket"} <= names


def test_optional_rca_explanation_does_not_block_async_service():
    started, release = Event(), Event()

    class Reasoner:
        def reason(self, report, *, focus):
            started.set()
            assert release.wait(3)
            return RcaReasoningResult.unavailable(
                RcaReasoningStatus.UNAVAILABLE, report
            )

    async def verify():
        server = create_rca_mcp_server(
            analysis_service=_FakeAnalysisService(), reasoner=Reasoner()
        )
        pending = asyncio.create_task(
            server.call_tool(
                "analyze_run", {"run_id": str(RUN_ID), "reasoning": "explain"}
            )
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 2), 2.5)
            independent = await asyncio.wait_for(
                server.call_tool("analyze_run", {"run_id": str(RUN_ID)}), 1
            )
            assert independent.structured_content is not None
        finally:
            release.set()
            await pending

    asyncio.run(verify())


def test_runtime_projection_covers_current_hardware_and_ticket_tools():
    names = (
        "get_maintenance_ticket",
        "get_position_reference_status",
        "prepare_reference_calibration",
        "execute_reference_calibration",
    )
    record = replace(
        _inspection(status=RunStatus.WAITING_FOR_APPROVAL, tool_names=names),
        data_classification=DataClassification.CONFIDENTIAL,
        run_profile=AgentRunProfile.CONFIDENTIAL_RECOVERY,
        approval_action="execute_reference_calibration",
    )
    server = _server(_FakeRuntimeStore(records=(record,)))

    async def verify():
        trajectory = await server.call_tool(
            "get_run_tool_trajectory", {"run_id": str(RUN_ID)}
        )
        approval = await server.call_tool("get_run_approval", {"run_id": str(RUN_ID)})
        assert len(trajectory.structured_content["trajectory"]) == 4
        assert approval.structured_content["action"] == "execute_reference_calibration"

    asyncio.run(verify())
    assert _safe_tool_names([{"tool": name} for name in names]) == names


@pytest.mark.parametrize("preparations", [2, 3])
def test_automatic_recovery_preparation_reserves_the_execution_budget(preparations):
    provider = HardwareRecoveryMcpToolProvider()
    sequence = ["prepare_reference_calibration"] * preparations + [
        "get_position_reference_status"
    ]
    responses = [
        LLMResponse(
            text=None,
            finish_reason=FinishReason.TOOL_CALLS,
            tool_calls=(
                LLMToolCall(
                    id=f"synthetic-{index}", name=name, arguments={"station_id": "S04"}
                ),
            ),
        )
        for index, name in enumerate(sequence)
    ]
    state, payload = asyncio.run(
        _agent(
            FakeLLMClient(responses),
            provider,
            InMemorySaver(),
            requires_verified_recovery=True,
        ).astart_via_mcp("Recover S04 position reference.", thread_id=str(uuid4()))
    )
    assert state["executed_tool_count"] <= MAX_TOOL_CALLS
    assert state["run_status"] == AgentRunStatus.LIMIT_REACHED
    assert payload is None
    assert provider.calls == []
