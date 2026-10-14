"""Deterministic regressions for the post-refactoring stabilization boundaries."""

import asyncio
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from openai import APIStatusError, OpenAI
from pydantic import ValidationError
from test_fastapi_api import FakeRunService, _success_result, create_app
from test_langgraph_mcp_hitl import (
    FakeLLMClient,
    HardwareRecoveryMcpToolProvider,
    _agent,
)
from test_openai_compatible_llm_client import (
    create_authenticated_configuration,
    create_configuration,
)
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
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_CONSUMER,
    CapabilityCheckedLLMClient,
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
from industrial_ai_agent.infrastructure.llm import openai_compatible as provider_adapter
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


_C03_ENDPOINT_CASES = [
    pytest.param(
        "https://remote.invalid/v1",
        "https://localhost/v1",
        PermissionError,
        id="remote-host",
    ),
    pytest.param(
        "http://127.0.0.1.evil.invalid/v1",
        "http://127.0.0.1/v1",
        PermissionError,
        id="deceptive-loopback-host",
    ),
    pytest.param(
        "http://user:password@localhost:11434/v1",
        "http://localhost:11434/v1",
        ValueError,
        id="url-userinfo",
    ),
]


def _endpoint_override_configuration():
    # Validate the complete catalog; only the supported environment override changes.
    configuration = create_configuration()
    payload = configuration.model_dump(mode="json", by_alias=True)
    payload["models"][0]["base_url_env"] = "TEST_MODEL_URL"
    return type(configuration).model_validate(payload)


class _EndpointRecordingSdk:
    def __init__(self):
        self.factories = []
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.complete))

    def factory(self, **kwargs):
        self.factories.append(kwargs)
        return self

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="SYNTHETIC", tool_calls=None),
                    finish_reason="stop",
                )
            ]
        )

    def close(self):
        for factory in self.factories:
            factory["http_client"].close()


@pytest.mark.parametrize("endpoint,allowed_endpoint,error_type", _C03_ENDPOINT_CASES)
def test_effective_local_destination_is_checked_before_sdk_creation(
    endpoint, allowed_endpoint, error_type, monkeypatch
):
    configuration = _endpoint_override_configuration()
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="SYNTHETIC"),)
    )
    environment = {"TEST_MODEL_URL": endpoint}
    sdk = _EndpointRecordingSdk()
    guard_calls = []
    guard_denials = []
    egress_calls = []
    original_guard = provider_adapter._validate_destination

    def guard(base_url, zone):
        guard_calls.append((base_url, zone))
        try:
            return original_guard(base_url, zone)
        except (ValueError, PermissionError) as error:
            guard_denials.append(type(error))
            raise

    class Authorizer(ModelExecutionAuthorizer):
        def require_allowed(self, classification, zone, maximum):
            egress_calls.append((classification, zone, maximum))
            return super().require_allowed(classification, zone, maximum)

    monkeypatch.setattr(provider_adapter, "_validate_destination", guard)
    adapter = OpenAICompatibleLLMClient(
        configuration, environment=environment, client_factory=sdk.factory
    )
    client = CapabilityCheckedLLMClient(
        EgressCheckedLLMClient(
            adapter,
            configuration,
            DataClassification.RESTRICTED,
            authorizer=Authorizer(),
        ),
        configuration,
        consumer_id=AGENT_CONSUMER,
        data_classification=DataClassification.RESTRICTED,
    )
    try:
        with pytest.raises(error_type) as denied:
            client.chat(ModelId("local_quality"), request)
        assert type(denied.value) is error_type
        assert guard_calls == [(endpoint, ExecutionZone.LOCAL)]
        assert guard_denials == [error_type]
        assert egress_calls == [
            (
                DataClassification.RESTRICTED,
                ExecutionZone.LOCAL,
                DataClassification.RESTRICTED,
            )
        ]
        assert sdk.factories == []
        assert sdk.calls == []

        # Same validated request, model, task and classification; change only the URL.
        environment["TEST_MODEL_URL"] = allowed_endpoint
        assert client.chat(ModelId("local_quality"), request).text == "SYNTHETIC"
        assert guard_calls == [
            (endpoint, ExecutionZone.LOCAL),
            (allowed_endpoint, ExecutionZone.LOCAL),
        ]
        assert guard_denials == [error_type]
        assert (
            egress_calls
            == [
                (
                    DataClassification.RESTRICTED,
                    ExecutionZone.LOCAL,
                    DataClassification.RESTRICTED,
                )
            ]
            * 2
        )
        assert len(sdk.factories) == len(sdk.calls) == 1
        assert sdk.calls[0]["messages"] == [{"role": "user", "content": "SYNTHETIC"}]
    finally:
        adapter.close()


@pytest.mark.parametrize("endpoint,allowed_endpoint,error_type", _C03_ENDPOINT_CASES)
def test_invalid_endpoint_fixture_stops_at_schema_before_the_guard(
    endpoint, allowed_endpoint, error_type, monkeypatch
):
    sdk = _EndpointRecordingSdk()
    reached = []
    monkeypatch.setattr(
        provider_adapter, "_validate_destination", lambda *args: reached.append(True)
    )
    adapter = OpenAICompatibleLLMClient(
        _endpoint_override_configuration(),
        environment={"TEST_MODEL_URL": endpoint},
        client_factory=sdk.factory,
    )
    try:
        with pytest.raises(ValidationError) as invalid:
            adapter.chat(ModelId("local_quality"), LLMRequest(messages=()))
        assert [(error["loc"], error["type"]) for error in invalid.value.errors()] == [
            (("messages",), "too_short")
        ]
        assert reached == []
        assert sdk.factories == sdk.calls == []
    finally:
        adapter.close()


@pytest.mark.parametrize("endpoint,allowed_endpoint,error_type", _C03_ENDPOINT_CASES)
def test_endpoint_regression_detects_guard_bypass(
    endpoint, allowed_endpoint, error_type, monkeypatch
):
    monkeypatch.setattr(provider_adapter, "_validate_destination", lambda *_: None)
    with pytest.raises(pytest.fail.Exception):
        test_effective_local_destination_is_checked_before_sdk_creation(
            endpoint, allowed_endpoint, error_type, monkeypatch
        )


@pytest.mark.parametrize("endpoint,allowed_endpoint,error_type", _C03_ENDPOINT_CASES)
def test_endpoint_regression_detects_a_matching_error_from_an_earlier_layer(
    endpoint, allowed_endpoint, error_type, monkeypatch
):
    def unrelated_denial(*args):
        raise error_type("Synthetic earlier validator rejection")

    monkeypatch.setattr(
        provider_adapter.OpenAICompatibleLLMClient, "chat", unrelated_denial
    )
    with pytest.raises(AssertionError):
        test_effective_local_destination_is_checked_before_sdk_creation(
            endpoint, allowed_endpoint, error_type, monkeypatch
        )


def test_known_c04_public_cloud_http_reaches_credential_bearing_transport(monkeypatch):
    """Observe C04 with valid inputs before declaring the known expected failure."""
    configuration = create_authenticated_configuration()
    payload = configuration.model_dump(mode="json", by_alias=True)
    payload["models"][0]["base_url_env"] = "TEST_MODEL_URL"
    configuration = type(configuration).model_validate(payload)
    guard_calls = []
    seen = []
    original_guard = provider_adapter._validate_destination

    def guard(endpoint, zone):
        guard_calls.append(zone)
        return original_guard(endpoint, zone)

    def transport(request):
        seen.append((request.url.scheme, bool(request.headers.get("authorization"))))
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "SYNTHETIC"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def factory(**kwargs):
        kwargs["http_client"].close()
        kwargs["http_client"] = httpx.Client(
            transport=httpx.MockTransport(transport),
            trust_env=False,
            follow_redirects=False,
        )
        return OpenAI(**kwargs)

    monkeypatch.setattr(provider_adapter, "_validate_destination", guard)
    adapter = OpenAICompatibleLLMClient(
        configuration,
        environment={
            "TEST_MODEL_URL": "http://provider.invalid/v1",
            "CLOUD_LLM_API_KEY": "synthetic-test-only-key",
        },
        client_factory=factory,
    )
    client = CapabilityCheckedLLMClient(
        EgressCheckedLLMClient(adapter, configuration, DataClassification.PUBLIC),
        configuration,
        consumer_id=AGENT_CONSUMER,
        data_classification=DataClassification.PUBLIC,
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="SYNTHETIC"),)
    )
    try:
        assert client.chat(ModelId("local_quality"), request).text == "SYNTHETIC"
        assert guard_calls == [ExecutionZone.PUBLIC_CLOUD]
        assert seen == [("http", True)]
        # Only the fully observed C04 condition becomes XFAIL; setup/guard errors fail.
        pytest.xfail(
            "Known C04: PUBLIC_CLOUD permits credential-bearing HTTP; synthetic MockTransport only"
        )
    finally:
        adapter.close()


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
