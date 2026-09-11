import asyncio
import logging
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    DocumentReference,
    ExecutedToolCall,
    InvestigationStep,
)
from industrial_ai_agent.agent.llm import LLMProviderError, LLMProviderErrorCode
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
from industrial_ai_agent.application.document_content import AuthorizedDocumentContent
from industrial_ai_agent.domain.closed_loop_recovery import RecoveryOutcome
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app as _create_app
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.api.schemas import RunResponse, RunStatus
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
        self.response_languages: list[ResponseLanguage | None] = []
        self.conversation_contexts: list[object] = []
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
        conversation_context: tuple[object, ...] = (),
    ) -> AgentRunResult:
        self.messages.append(message)
        self.response_languages.append(response_language)
        self.conversation_contexts.append(conversation_context)
        self.policies.append(run_policy)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class FakeDocumentContentReader:
    def __init__(self) -> None:
        self.contexts = []
        self.available = True

    def get_document(self, document_id: str, security_context):
        self.contexts.append((document_id, security_context))
        if (
            document_id != "doc-quality-procedure"
            or not self.available
            or security_context.clearance < DataClassification.CONFIDENTIAL
        ):
            return None
        return AuthorizedDocumentContent(
            content=b"authorized document bytes",
            media_type="text/markdown",
            filename="S04-QUALITY-09-Troubleshooting-Procedure.md",
        )


def create_app(
    run_service: FakeRunService,
    *,
    allowed_origins: tuple[str, ...] = (),
    document_content_reader: FakeDocumentContentReader | None = None,
    execution_timeout_seconds: float = 60.0,
):
    """Keep the in-memory adapter explicit and isolated to API unit tests."""
    return _create_app(
        run_service,
        run_store=InMemoryAgentRunStore(),
        allowed_origins=allowed_origins,
        document_content_reader=document_content_reader,
        execution_timeout_seconds=execution_timeout_seconds,
    )


class DelayedRunService(FakeRunService):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cancelled_calls = 0
        self.completed_calls = 0

    async def run_with_policy(self, *args, **kwargs):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.cancelled_calls += 1
            raise
        self.completed_calls += 1
        return await super().run_with_policy(*args, **kwargs)


def test_health_returns_ok() -> None:
    client = TestClient(create_app(FakeRunService(result=_success_result())))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_execution_timeout_persists_terminal_sanitized_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    store = InMemoryAgentRunStore()
    service = DelayedRunService(result=_success_result())
    app = _create_app(
        service,
        run_store=store,
        execution_timeout_seconds=0.001,
    )
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.api.app.uuid4", lambda: run_id
    )

    response = TestClient(app).post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == {
        "code": "agent_execution_timeout",
        "message": "The agent run exceeded its execution time limit.",
    }
    stored = asyncio.run(store.get(run_id))
    assert stored is not None
    assert stored.status is RunStatus.FAILED
    assert stored.error_code == "agent_execution_timeout"
    assert stored.result is None
    assert service.cancelled_calls == 1
    assert service.completed_calls == 0
    assert service.messages == []

    # wait_for awaits cancellation before returning, so a late completion cannot
    # overwrite the terminal failure or execute the delayed agent path.
    asyncio.run(asyncio.sleep(0))
    history = TestClient(app).get(
        f"/api/v1/investigations/{run_id}?user_clearance=CONFIDENTIAL"
    )
    assert history.status_code == 200
    assert history.json()["turns"][0]["status"] == "failed"
    assert history.json()["turns"][0]["error"] == {
        "code": "agent_execution_timeout",
        "message": "The agent run exceeded its execution time limit.",
    }
    pdf = TestClient(app).get(
        f"/api/v1/investigations/{run_id}/pdf?user_clearance=CONFIDENTIAL"
    )
    assert pdf.status_code == 200
    assert b"agent_execution_timeout" in pdf.content


def test_provider_failure_is_terminal_and_following_request_remains_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProviderFailureThenSuccessService(FakeRunService):
        def __init__(self) -> None:
            super().__init__(result=_success_result())
            self.calls = 0

        async def run_with_policy(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise LLMProviderError(
                    LLMProviderErrorCode.RATE_LIMIT,
                    provider_error_type="RateLimitError",
                )
            return await super().run_with_policy(*args, **kwargs)

    run_ids = iter(
        (
            UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
            UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
        )
    )
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.api.app.uuid4", lambda: next(run_ids)
    )
    store = InMemoryAgentRunStore()
    client = TestClient(
        _create_app(ProviderFailureThenSuccessService(), run_store=store)
    )

    blocked = client.post("/api/v1/runs", json=_confidential_request())
    recovered = client.post("/api/v1/runs", json=_confidential_request())

    assert blocked.status_code == 200
    assert blocked.json()["status"] == "failed"
    assert blocked.json()["error"]["code"] == "llm_rate_limit"
    assert recovered.status_code == 200
    failed_run = asyncio.run(store.get(UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")))
    assert failed_run is not None
    assert failed_run.status is RunStatus.FAILED
    assert failed_run.error_code == "llm_rate_limit"


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
        "investigation_id",
        "investigation_sequence",
        "status",
        "data_classification",
        "answer",
        "recovery_outcome",
        "investigation_steps",
        "next_steps",
        "identifiers",
        "documents",
        "tool_calls",
        "error",
        "approval_request",
    }
    assert RunResponse.model_validate(payload).model_dump(mode="json") == payload
    assert payload["status"] == "success"
    assert payload["investigation_id"] == payload["run_id"]
    assert payload["investigation_sequence"] == 1
    assert payload["data_classification"] == "CONFIDENTIAL"
    assert payload["answer"] == "P4711 failed at S04."
    assert payload["investigation_steps"] == [
        {
            "step": 1,
            "action": "get_product_history",
            "finding": "P4711 failed at S04.",
        }
    ]
    assert payload["next_steps"] == [
        "Check station S04.",
        "Search documentation for QUALITY-09.",
    ]
    assert payload["identifiers"] == []
    assert payload["documents"] == []
    assert payload["tool_calls"] == [
        {"tool": "get_product_history", "arguments": {"product_id": "P4711"}}
    ]
    assert payload["error"] is None
    assert payload["approval_request"] is None
    assert service.messages == ["Investigate product P4711."]

    stored_response = client.get(f"/api/v1/runs/{payload['run_id']}")

    assert stored_response.status_code == 200
    assert stored_response.json() == payload


@pytest.mark.parametrize(
    ("message", "selected_language"),
    (
        ("Untersuche P4711 an S04.", "EN"),
        ("Investigate P4711 at S04.", "DE"),
    ),
)
def test_explicit_response_language_overrides_request_detection(
    message: str, selected_language: str
) -> None:
    service = FakeRunService(result=_success_result())
    response = TestClient(create_app(service)).post(
        "/api/v1/runs",
        json={
            "message": message,
            "response_language": selected_language,
            "user_clearance": "CONFIDENTIAL",
        },
    )

    assert response.status_code == 200
    assert service.response_languages == [ResponseLanguage(selected_language)]


def test_public_run_response_accepts_the_maintenance_ticket_read_trajectory() -> None:
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="Das Ticket ist verfügbar.",
        tool_call_count=1,
        executed_tool_calls=(
            ExecutedToolCall(
                tool="get_maintenance_ticket",
                arguments={"ticket_id": "MT-6EA0DEF5515A"},
            ),
        ),
    )
    client = TestClient(create_app(FakeRunService(result=result)))

    response = client.post(
        "/api/v1/runs",
        json={
            "message": "Zeige mir das Ticket MT-6EA0DEF5515A.",
            "user_clearance": "CONFIDENTIAL",
        },
    )

    assert response.status_code == 200
    assert response.json()["tool_calls"] == [
        {
            "tool": "get_maintenance_ticket",
            "arguments": {"ticket_id": "MT-6EA0DEF5515A"},
        }
    ]


def test_investigation_history_groups_follow_ups_filters_clearance_and_exports_pdf() -> (
    None
):
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))
    first = client.post(
        "/api/v1/runs",
        json={
            "message": "Show ticket MT-6EA0DEF5515A.",
            "user_clearance": "CONFIDENTIAL",
        },
    ).json()
    second = client.post(
        "/api/v1/runs",
        json={
            "message": "Investigate P4711 at S04.",
            "user_clearance": "CONFIDENTIAL",
            "investigation_id": first["investigation_id"],
        },
    ).json()

    assert "investigation_id" in second, second
    assert second["investigation_id"] == first["investigation_id"]
    assert second["run_id"] != first["run_id"]
    assert second["investigation_sequence"] == 2
    assert len(service.conversation_contexts[-1]) == 1

    history = client.get(
        f"/api/v1/investigations/{first['investigation_id']}?user_clearance=CONFIDENTIAL"
    )
    assert history.status_code == 200
    payload = history.json()
    assert [turn["sequence"] for turn in payload["turns"]] == [1, 2]
    assert payload["turns"][0]["request"] == "Show ticket MT-6EA0DEF5515A."
    assert payload["turns"][0]["tool_calls"] == [
        {"tool": "get_product_history", "arguments": {"product_id": "P4711"}}
    ]
    assert payload["turns"][0]["next_steps"] == [
        "Check station S04.",
        "Search documentation for QUALITY-09.",
    ]
    assert payload["turns"][0]["investigation_steps"] == [
        {
            "step": 1,
            "action": "get_product_history",
            "finding": "P4711 failed at S04.",
        }
    ]
    assert (
        client.get(
            f"/api/v1/investigations/{first['investigation_id']}?user_clearance=PUBLIC"
        ).status_code
        == 404
    )

    pdf = client.get(
        f"/api/v1/investigations/{first['investigation_id']}/pdf?user_clearance=CONFIDENTIAL"
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.headers["content-disposition"].endswith(
        f'investigation-{first["investigation_id"]}.pdf"'
    )
    assert str(first["investigation_id"]).encode() in pdf.content
    assert b"Show ticket MT-6EA0DEF5515A." in pdf.content
    assert b"get_product_history" in pdf.content
    assert b"CONFIDENTIAL" in pdf.content
    assert b"Recommended Investigation Actions" in pdf.content
    assert b"Check station S04." in pdf.content
    assert b"Traceback" not in pdf.content


def test_pdf_renders_supported_markdown_and_structured_references_without_raw_syntax() -> (
    None
):
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer=(
            "### Heading\n\n**bold** and *italic* with `QUALITY-09`.\n\n"
            "- first item\n- second item\n\n"
            "| Column | Value |\n| --- | --- |\n| State | OPEN |"
        ),
        identifiers=({"value": "QUALITY-09", "type": "error_code"},),
        documents=(
            {
                "document_id": "doc-quality-procedure",
                "title": "Quality Procedure",
                "format": "markdown",
            },
        ),
        tool_call_count=0,
    )
    client = TestClient(
        create_app(
            FakeRunService(result=result),
            document_content_reader=FakeDocumentContentReader(),
        )
    )
    run = client.post(
        "/api/v1/runs",
        json={"message": "Investigate QUALITY-09.", "user_clearance": "CONFIDENTIAL"},
    ).json()

    pdf = client.get(
        f"/api/v1/investigations/{run['investigation_id']}/pdf?user_clearance=CONFIDENTIAL"
    )
    history = client.get(
        f"/api/v1/investigations/{run['investigation_id']}?user_clearance=CONFIDENTIAL"
    )

    assert pdf.status_code == 200
    assert history.status_code == 200
    assert history.json()["turns"][0]["identifiers"] == [
        {"value": "QUALITY-09", "type": "error_code"}
    ]
    assert history.json()["turns"][0]["documents"] == [
        {
            "document_id": "doc-quality-procedure",
            "title": "Quality Procedure",
            "format": "markdown",
        }
    ]
    assert b"Heading" in pdf.content
    assert b"bold" in pdf.content
    assert b"Quality Procedure" in pdf.content
    assert b"### Heading" not in pdf.content
    assert b"**bold**" not in pdf.content
    assert b"| Column |" not in pdf.content


def test_pdf_preserves_technical_identifiers_with_hyphen_minus_exactly() -> None:
    identifiers = (
        "QUALITY-09",
        "quality-related",
        "mis-calibrated",
        "doc-s04quality09procedure",
        "POSITION-ENC-02",
    )
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="\n".join(identifiers),
        tool_call_count=0,
    )
    client = TestClient(create_app(FakeRunService(result=result)))
    run = client.post(
        "/api/v1/runs",
        json={"message": "Inspect QUALITY-09.", "user_clearance": "CONFIDENTIAL"},
    ).json()

    pdf = client.get(
        f"/api/v1/investigations/{run['investigation_id']}/pdf?user_clearance=CONFIDENTIAL"
    )

    assert pdf.status_code == 200
    for identifier in identifiers:
        assert identifier.encode() in pdf.content


def test_document_open_and_download_reauthorize_each_request_without_storage_leaks() -> (
    None
):
    reader = FakeDocumentContentReader()
    client = TestClient(
        create_app(
            FakeRunService(result=_success_result()), document_content_reader=reader
        )
    )

    opened = client.get(
        "/api/v1/documents/doc-quality-procedure?user_clearance=CONFIDENTIAL"
    )
    downloaded = client.get(
        "/api/v1/documents/doc-quality-procedure/download?user_clearance=CONFIDENTIAL"
    )
    lowered_clearance = client.get(
        "/api/v1/documents/doc-quality-procedure?user_clearance=PUBLIC"
    )
    unknown = client.get("/api/v1/documents/unknown?user_clearance=CONFIDENTIAL")

    assert opened.status_code == 200
    assert opened.headers["content-type"].startswith("text/markdown")
    assert opened.headers["content-disposition"] == (
        'inline; filename="S04-QUALITY-09-Troubleshooting-Procedure.md"'
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"] == (
        'attachment; filename="S04-QUALITY-09-Troubleshooting-Procedure.md"'
    )
    assert lowered_clearance.status_code == unknown.status_code == 404
    assert (
        lowered_clearance.json()
        == unknown.json()
        == {
            "code": "document_not_available",
            "message": "The requested document is not available.",
        }
    )
    assert all("demo_factory" not in value for value in opened.headers.values())
    assert all("http" not in value for value in opened.headers.values())
    assert [context.clearance for _, context in reader.contexts] == [
        DataClassification.CONFIDENTIAL,
        DataClassification.CONFIDENTIAL,
        DataClassification.PUBLIC,
        DataClassification.CONFIDENTIAL,
    ]


def test_run_and_history_publish_only_currently_authorized_usable_documents() -> None:
    reader = FakeDocumentContentReader()
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="Documentation was consulted.",
        tool_call_count=0,
        documents=(
            DocumentReference(
                document_id="doc-quality-procedure",
                title="S04 QUALITY-09 Troubleshooting Procedure",
                format="markdown",
            ),
            DocumentReference(
                document_id="doc-without-content",
                title="Must not be published",
                format="pdf",
            ),
        ),
    )
    client = TestClient(
        create_app(FakeRunService(result=result), document_content_reader=reader)
    )

    created = client.post("/api/v1/runs", json=_confidential_request())

    assert created.status_code == 200
    assert created.json()["documents"] == [
        {
            "document_id": "doc-quality-procedure",
            "title": "S04 QUALITY-09 Troubleshooting Procedure",
            "format": "markdown",
        }
    ]
    assert "Must not be published" not in created.text
    investigation_id = created.json()["investigation_id"]
    history = client.get(
        f"/api/v1/investigations/{investigation_id}?user_clearance=CONFIDENTIAL"
    )
    assert history.status_code == 200
    assert history.json()["turns"][0]["documents"] == created.json()["documents"]

    # A persisted reference is not a permanent authorization token.
    reader.available = False
    reconstructed = client.get(
        f"/api/v1/investigations/{investigation_id}?user_clearance=CONFIDENTIAL"
    )
    assert reconstructed.status_code == 200
    assert reconstructed.json()["turns"][0]["documents"] == []
    assert "S04 QUALITY-09 Troubleshooting Procedure" not in reconstructed.text


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


@pytest.mark.parametrize(
    ("message", "clearance", "classification"),
    (
        (
            "Liste die mir verfügbaren Produkte auf und fasse ihren Endstatus zusammen.",
            "PUBLIC",
            "PUBLIC",
        ),
        (
            "Gib mir einen Überblick über die mir verfügbaren Produkte und ihren Endstatus.",
            "INTERNAL",
            "INTERNAL",
        ),
        (
            "Untersuche Produkt P4801 und fasse seinen sichtbaren Produktionspfad zusammen.",
            "CONFIDENTIAL",
            "CONFIDENTIAL",
        ),
        (
            "Ermittle die kürzlich fehlgeschlagenen Produkte und fasse ihren Fehlerstatus zusammen.",
            "CONFIDENTIAL",
            "CONFIDENTIAL",
        ),
        (
            "Untersuche die Produktionshistorie von P4101.",
            "PUBLIC",
            "PUBLIC",
        ),
    ),
)
def test_german_product_requests_use_their_authorized_run_scope(
    message: str, clearance: str, classification: str
) -> None:
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={"message": message, "user_clearance": clearance},
    )

    assert response.status_code == 200
    assert response.json()["data_classification"] == classification
    assert service.policies[0].data_classification.name == classification


def test_confidential_ticket_lookup_uses_the_bounded_ticket_trajectory() -> None:
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="Das Ticket ist sichtbar.",
        tool_call_count=1,
        executed_tool_calls=(
            ExecutedToolCall(
                tool="get_maintenance_ticket",
                arguments={"ticket_id": "MT-S02-20260117"},
            ),
        ),
    )
    service = FakeRunService(result=result)
    client = TestClient(create_app(service))

    response = client.post(
        "/api/v1/runs",
        json={
            "message": "Zeige die verfügbaren Details zum Wartungsticket MT-S02-20260117.",
            "user_clearance": "CONFIDENTIAL",
        },
    )

    assert response.status_code == 200
    assert response.json()["data_classification"] == "CONFIDENTIAL"
    assert response.json()["tool_calls"] == [
        {
            "tool": "get_maintenance_ticket",
            "arguments": {"ticket_id": "MT-S02-20260117"},
        }
    ]
    assert service.response_languages == [ResponseLanguage.DE]
    assert service.policies[0].data_classification is DataClassification.CONFIDENTIAL


def test_recovery_incomplete_is_a_failed_run_with_a_bounded_error_code() -> None:
    result = AgentRunResult(
        status=AgentRunStatus.RECOVERY_INCOMPLETE,
        final_answer="The required recovery preparation was not performed.",
        tool_call_count=1,
        executed_tool_calls=(
            ExecutedToolCall(
                tool="get_position_reference_status",
                arguments={"station_id": "S04"},
            ),
        ),
    )
    client = TestClient(create_app(FakeRunService(result=result)))

    response = client.post(
        "/api/v1/runs",
        json={
            "message": "Recover the position reference at S04.",
            "user_clearance": "CONFIDENTIAL",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == {
        "code": "recovery_incomplete",
        "message": "The requested recovery was not completed.",
    }
    assert response.json()["tool_calls"] == [
        {
            "tool": "get_position_reference_status",
            "arguments": {"station_id": "S04"},
        }
    ]


def test_recovery_not_required_is_a_successful_no_action_run_and_pdf_protocol() -> None:
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer=(
            "No recovery is required. The position reference at station S04 is already valid."
        ),
        recovery_outcome=RecoveryOutcome.NOT_REQUIRED,
        tool_call_count=1,
        executed_tool_calls=(
            ExecutedToolCall(
                tool="get_position_reference_status",
                arguments={"station_id": "S04"},
            ),
        ),
    )
    client = TestClient(create_app(FakeRunService(result=result)))

    response = client.post(
        "/api/v1/runs",
        json={
            "message": "Recover the position reference at S04.",
            "user_clearance": "CONFIDENTIAL",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["recovery_outcome"] == "NOT_REQUIRED"
    assert response.json()["approval_request"] is None
    assert response.json()["tool_calls"] == [
        {
            "tool": "get_position_reference_status",
            "arguments": {"station_id": "S04"},
        }
    ]

    pdf = client.get(
        f"/api/v1/investigations/{response.json()['investigation_id']}/pdf?user_clearance=CONFIDENTIAL"
    )
    assert pdf.status_code == 200
    assert b"No action was required." in pdf.content


def test_internal_ticket_lookup_is_neutral_and_indistinguishable_from_unknown_ticket() -> (
    None
):
    service = FakeRunService(result=_success_result())
    client = TestClient(create_app(service))

    hidden_response = client.post(
        "/api/v1/runs",
        json={
            "message": "Zeige das Wartungsticket MT-S02-20260117.",
            "user_clearance": "INTERNAL",
        },
    )
    unknown_response = client.post(
        "/api/v1/runs",
        json={
            "message": "Zeige das Wartungsticket MT-S99-20991231.",
            "user_clearance": "INTERNAL",
        },
    )

    assert hidden_response.status_code == unknown_response.status_code == 404
    assert (
        hidden_response.json()
        == unknown_response.json()
        == {
            "code": "requested_data_unavailable",
            "message": "Die angeforderten Daten sind nicht verfügbar.",
        }
    )
    assert "MT-S02-20260117" not in hidden_response.text
    assert "CONFIDENTIAL" not in hidden_response.text
    assert service.messages == []
    assert service.policies == []


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


def test_no_eligible_model_returns_a_persisted_failed_run() -> None:
    client = TestClient(
        create_app(
            FakeRunService(
                error=NoEligibleModelError(confidential_troubleshooting_requirements())
            )
        )
    )

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"]["code"] == "no_eligible_model"


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


def test_mcp_unavailability_returns_a_persisted_failed_run() -> None:
    client = TestClient(
        create_app(FakeRunService(error=McpServiceUnavailableError("unavailable")))
    )

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == {
        "code": "mcp_service_unavailable",
        "message": "A required MCP service is unavailable.",
    }


@pytest.mark.parametrize(
    ("code", "language", "message"),
    (
        (
            LLMProviderErrorCode.RATE_LIMIT,
            "EN",
            (
                "The language model is temporarily unavailable because its usage "
                "limit has been reached. Please try again later."
            ),
        ),
        (
            LLMProviderErrorCode.QUOTA_EXCEEDED,
            "DE",
            (
                "Das Sprachmodell ist aufgrund eines Nutzungslimits vorübergehend "
                "nicht verfügbar. Bitte versuchen Sie es später erneut."
            ),
        ),
        (
            LLMProviderErrorCode.PROVIDER_UNAVAILABLE,
            "EN",
            (
                "The language model provider is temporarily unavailable. Please try "
                "again later."
            ),
        ),
    ),
)
def test_llm_provider_limit_is_sanitized_persisted_and_available_in_history(
    code: LLMProviderErrorCode,
    language: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    store = InMemoryAgentRunStore()
    app = _create_app(
        FakeRunService(
            error=LLMProviderError(
                code,
                provider_error_type="RateLimitError",
            )
        ),
        run_store=store,
    )
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.api.app.uuid4", lambda: run_id
    )

    response = TestClient(app).post(
        "/api/v1/runs",
        json={
            **_confidential_request(),
            "response_language": language,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == {"code": code.value, "message": message}
    assert "RateLimitError" not in response.text
    stored = asyncio.run(store.get(run_id))
    assert stored is not None
    assert stored.status is RunStatus.FAILED
    assert stored.error_code == code.value

    history = TestClient(app).get(
        f"/api/v1/investigations/{run_id}?user_clearance=CONFIDENTIAL"
    )

    assert history.status_code == 200
    assert history.json()["turns"][0]["error"] == {
        "code": code.value,
        "message": message,
    }


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message"),
    (
        (
            McpServiceUnavailableError("unavailable"),
            "mcp_service_unavailable",
            "A required MCP service is unavailable.",
        ),
        (
            LLMProviderError(
                LLMProviderErrorCode.RATE_LIMIT,
                provider_error_type="RateLimitError",
            ),
            "llm_rate_limit",
            (
                "The language model is temporarily unavailable because its usage "
                "limit has been reached. Please try again later."
            ),
        ),
    ),
)
def test_pdf_exports_persisted_operational_failure_transcripts(
    error: Exception,
    expected_code: str,
    expected_message: str,
) -> None:
    client = TestClient(create_app(FakeRunService(error=error)))

    run = client.post("/api/v1/runs", json=_confidential_request()).json()
    pdf = client.get(
        f"/api/v1/investigations/{run['investigation_id']}/pdf?user_clearance=CONFIDENTIAL"
    )

    assert run["status"] == "failed"
    assert run["investigation_steps"] == []
    assert pdf.status_code == 200
    assert b"Investigate P4711." in pdf.content
    assert expected_code.encode() in pdf.content
    assert expected_message.split()[0].encode() in pdf.content
    assert expected_message.split()[-2].encode() in pdf.content
    assert b"Status:" in pdf.content


@pytest.mark.parametrize(
    ("status", "error_code", "answer"),
    (
        (
            AgentRunStatus.RECOVERY_INCOMPLETE,
            "recovery_incomplete",
            "The requested recovery was not completed.",
        ),
        (
            AgentRunStatus.RECOVERY_BLOCKED,
            "recovery_blocked",
            "The requested recovery was blocked.",
        ),
    ),
)
def test_pdf_exports_recovery_failure_without_investigation_steps(
    status: AgentRunStatus, error_code: str, answer: str
) -> None:
    result = AgentRunResult(
        status=status,
        final_answer=answer,
        tool_call_count=0,
    )
    client = TestClient(create_app(FakeRunService(result=result)))

    run = client.post("/api/v1/runs", json=_confidential_request()).json()
    pdf = client.get(
        f"/api/v1/investigations/{run['investigation_id']}/pdf?user_clearance=CONFIDENTIAL"
    )

    assert run["status"] == "failed"
    assert run["investigation_steps"] == []
    assert run["error"]["code"] == error_code
    assert pdf.status_code == 200
    assert answer.encode() in pdf.content
    assert error_code.encode() in pdf.content


def test_unrelated_http_429_remains_an_internal_error() -> None:
    external_error = httpx.HTTPStatusError(
        "non-LLM 429 must not become a provider limit",
        request=httpx.Request("GET", "https://unrelated.example.test/resource"),
        response=httpx.Response(429),
    )
    client = TestClient(create_app(FakeRunService(error=external_error)))

    response = client.post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"


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

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"]["code"] == "mcp_service_unavailable"


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


def test_exception_group_logs_sanitized_inner_diagnostic_and_persists_failure(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    store = InMemoryAgentRunStore()
    app = _create_app(
        FakeRunService(
            error=ExceptionGroup(
                "unsafe outer details",
                [
                    ExceptionGroup(
                        "unsafe nested details",
                        [
                            ValueError(
                                "prompt=do not log; document contents=do not log; "
                                "token=do not log"
                            )
                        ],
                    )
                ],
            )
        ),
        run_store=store,
    )
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.api.app.uuid4", lambda: run_id
    )
    caplog.set_level(
        logging.ERROR, logger="industrial_ai_agent.api.failure_diagnostics"
    )

    response = TestClient(app).post("/api/v1/runs", json=_confidential_request())

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "The agent run could not be completed.",
    }
    stored = asyncio.run(store.get(run_id))
    assert stored is not None
    assert stored.status is RunStatus.FAILED
    assert stored.error_code == "internal_error"
    assert "exception_group=ExceptionGroup" in caplog.text
    assert "exception_type=ValueError" in caplog.text
    assert "operation=langgraph_execution" in caplog.text
    assert "error_code=invalid_runtime_value" in caplog.text
    assert "invalid runtime value" in caplog.text
    assert "prompt=do not log" not in caplog.text
    assert "document contents=do not log" not in caplog.text
    assert "token=do not log" not in caplog.text


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
        investigation_steps=(
            InvestigationStep(
                step=1,
                action="get_product_history",
                finding="P4711 failed at S04.",
            ),
        ),
        next_steps=(
            "Check station S04.",
            "Search documentation for QUALITY-09.",
        ),
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
