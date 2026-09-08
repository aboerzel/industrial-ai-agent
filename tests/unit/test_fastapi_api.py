import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    ExecutedToolCall,
)
from industrial_ai_agent.agent.model_egress import ModelEgressDeniedError
from industrial_ai_agent.agent.model_routing import NoEligibleModelError
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
    InternalDiagnosticTarget,
    ResolvedRunPolicy,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    InternalDiagnosticTargetUnavailableError,
    McpServiceUnavailableError,
    confidential_troubleshooting_requirements,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app as _create_app
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.api.schemas import RunResponse
from industrial_ai_agent.infrastructure.troubleshooting_run_composition import (
    create_default_troubleshooting_run_service,
)


class FakeRunService:
    def __init__(
        self,
        *,
        result: AgentRunResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.messages: list[str] = []
        self.policies: list[ResolvedRunPolicy] = []
        self.internal_target_available = True

    async def run(self, message: str) -> AgentRunResult:
        self.messages.append(message)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    async def resolve_internal_diagnostic(
        self, target: InternalDiagnosticTarget
    ) -> ResolvedRunPolicy:
        if not self.internal_target_available:
            raise InternalDiagnosticTargetUnavailableError("unavailable")
        assert target.product_id == "P4900"
        assert target.station_id == "S02"
        return AgentRunClassificationPolicy().resolve(
            AgentRunProfile.INTERNAL_DIAGNOSTIC
        )

    async def run_with_policy(
        self,
        message: str,
        *,
        run_policy: ResolvedRunPolicy,
        response_language: ResponseLanguage | None = None,
    ) -> AgentRunResult:
        del response_language
        self.messages.append(message)
        self.policies.append(run_policy)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def create_app(
    run_service: FakeRunService,
    *,
    allowed_origins: tuple[str, ...] = (),
):
    """Keep the in-memory adapter explicit and isolated to API unit tests."""
    return _create_app(
        run_service,
        run_store=InMemoryAgentRunStore(),
        allowed_origins=allowed_origins,
    )


def test_health_returns_ok() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_only_configured_development_origin() -> None:
    client = TestClient(
        create_app(
            FakeRunService(result=_success_result()),
            allowed_origins=("http://localhost:8080",),
        )
    )

    response = client.options(
        "/api/v1/runs",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert response.headers["access-control-allow-methods"] == "GET, POST"


def test_cors_rejects_unconfigured_origin() -> None:
    client = TestClient(
        create_app(
            FakeRunService(result=_success_result()),
            allowed_origins=("http://localhost:8080",),
        )
    )

    response = client.options(
        "/api/v1/runs",
        headers={
            "Origin": "http://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_create_run_returns_stable_public_schema_and_can_be_read() -> None:
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={
            "message": "  Investigate product P4711.  ",
            "user_clearance": "CONFIDENTIAL",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "run_id",
        "status",
        "data_classification",
        "answer",
        "tool_calls",
        "approval_request",
    }
    assert RunResponse.model_validate(payload).model_dump(mode="json") == payload
    assert payload["status"] == "success"
    assert payload["data_classification"] == "CONFIDENTIAL"
    assert payload["answer"] == "P4711 failed at S04."
    assert payload["tool_calls"] == [
        {"tool": "get_product_history", "arguments": {"product_id": "P4711"}}
    ]
    assert payload["approval_request"] is None
    assert service.messages == ["Investigate product P4711."]

    stored_response = client.get(f"/api/v1/runs/{payload['run_id']}")

    assert stored_response.status_code == 200
    assert stored_response.json() == payload


def test_create_run_uses_fastapi_validation_for_invalid_request() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.post("/api/v1/runs", json={"message": "   "})

    assert response.status_code == 422


def test_create_run_rejects_unknown_request_fields_fail_closed() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.post(
        "/api/v1/runs",
        json={"message": "Investigate P4711.", "classification": "INTERNAL"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("field", ("profile", "clearance", "mcp_identity", "model"))
def test_create_run_rejects_all_client_controlled_security_fields(field: str) -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.post(
        "/api/v1/runs",
        json={"message": "Investigate P4711.", field: "INTERNAL"},
    )

    assert response.status_code == 422


def test_demo_clearance_cannot_lower_unknown_free_text_classification() -> None:
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={
            "message": "What capabilities does the troubleshooting agent provide?",
            "user_clearance": "RESTRICTED",
        },
    )

    assert response.status_code == 200
    assert response.json()["data_classification"] == "RESTRICTED"
    assert service.policies[0].data_classification is DataClassification.RESTRICTED
    assert service.policies[0].mcp_clearance_ceiling is DataClassification.RESTRICTED
    assert service.policies[0].mcp_client_identity == "industrial-agent-restricted"


@pytest.mark.parametrize("clearance", ("PUBLIC", "INTERNAL"))
def test_insufficient_demo_clearance_cannot_start_confidential_case_or_invoke_a_model(
    clearance: str,
) -> None:
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={"message": "Investigate P4711 at S04.", "user_clearance": clearance},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "requested_data_unavailable"
    assert service.messages == []


@pytest.mark.parametrize("clearance", ("CONFIDENTIAL", "RESTRICTED"))
def test_sufficient_demo_clearance_keeps_confidential_case_at_confidential_ceiling(
    clearance: str,
) -> None:
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={"message": "Investigate P4711 at S04.", "user_clearance": clearance},
    )

    assert response.status_code == 200
    assert response.json()["data_classification"] == "CONFIDENTIAL"
    assert service.policies[0].data_classification is DataClassification.CONFIDENTIAL
    assert service.policies[0].mcp_clearance_ceiling is DataClassification.CONFIDENTIAL
    assert service.policies[0].mcp_client_identity == "industrial-agent"


def test_confidential_demo_user_cannot_start_restricted_case_or_invoke_a_model() -> (
    None
):
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={"message": "Investigate P9001 at S07.", "user_clearance": "CONFIDENTIAL"},
    )

    assert response.status_code == 404
    assert service.messages == []


def test_restricted_demo_user_runs_restricted_case_with_restricted_policy() -> None:
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={"message": "Investigate P9001 at S07.", "user_clearance": "RESTRICTED"},
    )

    assert response.status_code == 200
    assert response.json()["data_classification"] == "RESTRICTED"
    assert service.policies[0].data_classification is DataClassification.RESTRICTED
    assert service.policies[0].mcp_client_identity == "industrial-agent-restricted"


def test_structured_internal_diagnostic_uses_only_server_resolved_policy() -> None:
    service = FakeRunService(result=_success_result())
    app = create_app(service)
    client = TestClient(app)

    response = client.post(
        "/api/v1/diagnostics", json={"product_id": "P4900", "station_id": "S02"}
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    stored = asyncio.run(app.state.run_store.get(UUID(run_id)))
    assert stored is not None
    assert stored.run_profile is AgentRunProfile.INTERNAL_DIAGNOSTIC
    assert stored.data_classification is DataClassification.INTERNAL
    assert service.policies == [
        AgentRunClassificationPolicy().resolve(AgentRunProfile.INTERNAL_DIAGNOSTIC)
    ]
    assert "P4900" in service.messages[0]
    assert "S02" in service.messages[0]


def test_internal_diagnostic_does_not_expose_unavailable_target() -> None:
    service = FakeRunService(result=_success_result())
    service.internal_target_available = False
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/diagnostics", json={"product_id": "P4711", "station_id": "S04"}
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": "diagnostic_target_unavailable",
        "message": "The requested diagnostic target is unavailable.",
    }


def test_resume_rejects_unknown_decision_before_run_lookup() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.post(
        "/api/v1/runs/0ca96c57-66f6-4e12-b151-6f7f6ef9c9f8/resume",
        json={"decision": "later"},
    )

    assert response.status_code == 422


def test_successful_public_response_sanitizes_diagnostic_text() -> None:
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="Traceback (most recent call last): postgresql://user:password@db",
        tool_call_count=0,
    )
    client = TestClient(create_app(FakeRunService(result=result)))

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 200
    assert response.json()["answer"] == (
        "The requested result contains non-public diagnostic data."
    )
    assert "postgresql" not in response.text


def test_get_unknown_run_returns_sanitized_not_found_error() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.get("/api/v1/runs/0ca96c57-66f6-4e12-b151-6f7f6ef9c9f8")

    assert response.status_code == 404
    assert response.json() == {
        "code": "run_not_found",
        "message": "The requested run does not exist.",
    }


def test_no_eligible_model_maps_to_service_unavailable() -> None:
    client = TestClient(
        create_app(
            FakeRunService(
                error=NoEligibleModelError(confidential_troubleshooting_requirements())
            )
        )
    )

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 503
    assert response.json()["code"] == "no_eligible_model"


def test_model_egress_denial_fails_closed() -> None:
    client = TestClient(
        create_app(FakeRunService(error=ModelEgressDeniedError("denied")))
    )

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 403
    assert response.json() == {
        "code": "model_egress_denied",
        "message": "Model execution is not permitted for this request.",
    }


def test_mcp_unavailability_maps_to_service_unavailable() -> None:
    client = TestClient(
        create_app(FakeRunService(error=McpServiceUnavailableError("unavailable")))
    )

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 503
    assert response.json() == {
        "code": "mcp_service_unavailable",
        "message": "A required MCP service is unavailable.",
    }


def test_streamable_http_connection_failure_maps_to_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_INDUSTRIAL_AGENT_TOKEN", "unit-test-token")
    service = create_default_troubleshooting_run_service(
        factory_mcp_url="http://127.0.0.1:1/mcp",
        knowledge_mcp_url="http://127.0.0.1:1/mcp",
    )
    client = TestClient(create_app(service))

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 503
    assert response.json()["code"] == "mcp_service_unavailable"


@pytest.mark.parametrize(
    "error",
    (
        RuntimeError("secret endpoint details"),
        ExceptionGroup(
            "transport failure",
            [RuntimeError("secret nested diagnostic")],
        ),
    ),
)
def test_unexpected_failure_does_not_expose_internal_details(error: Exception) -> None:
    client = TestClient(create_app(FakeRunService(error=error)))

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "The agent run could not be completed.",
    }
    assert "secret" not in response.text


def test_openapi_contains_only_public_run_contracts() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    schema = client.get("/openapi.json").json()

    assert "/api/v1/runs" in schema["paths"]
    assert "/api/v1/runs/{run_id}" in schema["paths"]
    assert "CreateRunRequest" in schema["components"]["schemas"]
    assert "RunResponse" in schema["components"]["schemas"]
    assert "AgentRunResult" not in schema["components"]["schemas"]
    assert "McpToolSession" not in schema["components"]["schemas"]


def _success_result() -> AgentRunResult:
    return AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="P4711 failed at S04.",
        tool_call_count=1,
        executed_tool_calls=(
            ExecutedToolCall(
                tool="get_product_history",
                arguments={"product_id": "P4711"},
            ),
        ),
    )


def _confidential_request() -> dict[str, str]:
    return {"message": "Investigate P4711.", "user_clearance": "CONFIDENTIAL"}
