from fastapi.testclient import TestClient

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    ExecutedToolCall,
)
from industrial_ai_agent.agent.model_egress import ModelEgressDeniedError
from industrial_ai_agent.agent.model_routing import NoEligibleModelError
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpServiceUnavailableError,
    confidential_troubleshooting_requirements,
)
from industrial_ai_agent.infrastructure.api.app import create_app as _create_app
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
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

    async def run(self, message: str) -> AgentRunResult:
        self.messages.append(message)
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
        json={"message": "  Investigate product P4711.  "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["answer"] == "P4711 failed at S04."
    assert payload["tool_calls"] == [
        {"tool": "get_product_history", "arguments": {"product_id": "P4711"}}
    ]
    assert service.messages == ["Investigate product P4711."]

    stored_response = client.get(f"/api/v1/runs/{payload['run_id']}")

    assert stored_response.status_code == 200
    assert stored_response.json() == payload


def test_create_run_uses_fastapi_validation_for_invalid_request() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.post("/api/v1/runs", json={"message": "   "})

    assert response.status_code == 422


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

    response = client.post("/api/v1/runs", json={"message": "Investigate P4711."})

    assert response.status_code == 503
    assert response.json()["code"] == "no_eligible_model"


def test_model_egress_denial_fails_closed() -> None:
    client = TestClient(
        create_app(FakeRunService(error=ModelEgressDeniedError("denied")))
    )

    response = client.post("/api/v1/runs", json={"message": "Investigate P4711."})

    assert response.status_code == 403
    assert response.json() == {
        "code": "model_egress_denied",
        "message": "Model execution is not permitted for this request.",
    }


def test_mcp_unavailability_maps_to_service_unavailable() -> None:
    client = TestClient(
        create_app(FakeRunService(error=McpServiceUnavailableError("unavailable")))
    )

    response = client.post("/api/v1/runs", json={"message": "Investigate P4711."})

    assert response.status_code == 503
    assert response.json() == {
        "code": "mcp_service_unavailable",
        "message": "A required MCP service is unavailable.",
    }


def test_streamable_http_connection_failure_maps_to_service_unavailable() -> None:
    service = create_default_troubleshooting_run_service(
        factory_mcp_url="http://127.0.0.1:1/mcp",
        knowledge_mcp_url="http://127.0.0.1:1/mcp",
    )
    client = TestClient(create_app(service))

    response = client.post("/api/v1/runs", json={"message": "Investigate P4711."})

    assert response.status_code == 503
    assert response.json()["code"] == "mcp_service_unavailable"


def test_unexpected_failure_does_not_expose_internal_details() -> None:
    client = TestClient(
        create_app(FakeRunService(error=RuntimeError("secret endpoint details")))
    )

    response = client.post("/api/v1/runs", json={"message": "Investigate P4711."})

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
