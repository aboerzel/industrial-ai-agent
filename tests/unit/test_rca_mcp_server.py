import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.application.rca import (
    RcaAnalysisReport,
    RcaAnalysisStatus,
    RcaCompleteness,
    RcaComponent,
    RcaConfidence,
    RcaEvidenceBundle,
    RcaEvidenceSource,
    RcaEvidenceSourceStatus,
    RcaFinding,
    RcaFindingCategory,
    RcaFindingKind,
    RcaLimitationCode,
    RcaMeasurement,
    RcaMeasurementName,
    RcaMeasurementProvenance,
    RcaMeasurementScope,
    RcaMeasurementUnit,
    RcaRuntimeEvidence,
    RcaRuntimeStatus,
    RcaSeverity,
    RcaSourceAvailability,
)
from industrial_ai_agent.application.rca_evidence import RcaRunNotAccessibleError
from industrial_ai_agent.application.rca_reasoning import (
    RcaFocus,
    RcaReasoningAssessment,
    RcaReasoningResult,
    RcaReasoningStatus,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.mcp_access_control import (
    DemoBearerTokenAuthenticator,
    McpAuthorizationError,
    McpHttpAccessControl,
    RegisteredMcpClientContextResolver,
    _registration,
)
from industrial_ai_agent.infrastructure.rca_mcp_server import (
    _RCA_TOOL_PERMISSIONS,
    RCA_MCP_SERVER_NAME,
    create_rca_mcp_server,
)

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
NOW = datetime(2026, 9, 6, tzinfo=UTC)


def test_rca_mcp_exposes_only_one_strict_read_only_tool() -> None:
    server = create_rca_mcp_server(analysis_service=_FakeAnalysisService())  # type: ignore[arg-type]
    tools = asyncio.run(server.list_tools())

    assert RCA_MCP_SERVER_NAME == "rca_mcp"
    assert [tool.name for tool in tools] == ["analyze_run"]
    assert tools[0].annotations.read_only_hint
    assert tools[0].input_schema["additionalProperties"] is False
    assert set(tools[0].input_schema["properties"]) == {
        "run_id",
        "focus",
        "reasoning",
    }


def test_rca_mcp_validates_canonical_uuid_focus_and_extra_fields() -> None:
    server = create_rca_mcp_server(analysis_service=_FakeAnalysisService())  # type: ignore[arg-type]

    async def call() -> None:
        with pytest.raises(ToolError):
            await server.call_tool("analyze_run", {"run_id": str(RUN_ID).upper()})
        with pytest.raises(ToolError):
            await server.call_tool("analyze_run", {"run_id": "not-a-uuid"})
        with pytest.raises(ToolError):
            await server.call_tool(
                "analyze_run", {"run_id": str(RUN_ID), "focus": "latency"}
            )
        with pytest.raises(ToolError):
            await server.call_tool(
                "analyze_run", {"run_id": str(RUN_ID), "reasoning": "chat"}
            )
        with pytest.raises(ToolError):
            await server.call_tool(
                "analyze_run", {"run_id": str(RUN_ID), "unexpected": "value"}
            )

    asyncio.run(call())


def test_read_rca_is_dedicated_and_not_implied_by_runtime_access() -> None:
    registration = _registration(
        token="test-token",
        client_id="runtime-only",
        clearance=DataClassification.INTERNAL,
        permissions=frozenset({McpPermission.READ_AGENT_RUNTIME}),
    )
    permitted = _registration(
        token="rca-token",
        client_id="rca-reader",
        clearance=DataClassification.INTERNAL,
        permissions=frozenset({McpPermission.READ_RCA}),
    )
    access = McpHttpAccessControl(
        authenticator=DemoBearerTokenAuthenticator((registration, permitted)),
        resolver=RegisteredMcpClientContextResolver((registration, permitted)),
        tools=lambda: _tools(),
        required_permission=lambda name: _RCA_TOOL_PERMISSIONS[name],
    )

    denied = access.access_context_from_headers({"authorization": "Bearer test-token"})
    allowed = access.access_context_from_headers({"authorization": "Bearer rca-token"})

    with pytest.raises(McpAuthorizationError, match="MCP tool is not authorized"):
        access.authorize_tool(denied, "analyze_run")
    access.authorize_tool(allowed, "analyze_run")


def test_read_rca_filters_tool_discovery_for_an_identity_without_permission() -> None:
    registration = _registration(
        token="runtime-only-token",
        client_id="runtime-only",
        clearance=DataClassification.INTERNAL,
        permissions=frozenset({McpPermission.READ_AGENT_RUNTIME}),
    )
    allowed = _registration(
        token="rca-reader-token",
        client_id="rca-reader",
        clearance=DataClassification.INTERNAL,
        permissions=frozenset({McpPermission.READ_RCA}),
    )
    server = create_rca_mcp_server(analysis_service=_FakeAnalysisService())  # type: ignore[arg-type]
    access = McpHttpAccessControl(
        authenticator=DemoBearerTokenAuthenticator((registration, allowed)),
        resolver=RegisteredMcpClientContextResolver((registration, allowed)),
        tools=server.list_tools,
        required_permission=lambda name: _RCA_TOOL_PERMISSIONS[name],
    )

    denied_context = access.access_context_from_headers(
        {"authorization": "Bearer runtime-only-token"}
    )
    allowed_context = access.access_context_from_headers(
        {"authorization": "Bearer rca-reader-token"}
    )

    assert asyncio.run(access.visible_tools(denied_context)) == []
    assert [
        tool.name for tool in asyncio.run(access.visible_tools(allowed_context))
    ] == ["analyze_run"]


def test_overview_projection_preserves_findings_and_safe_boundary() -> None:
    result = _call("overview")

    assert result["focus"] == "overview"
    assert result["analysis_status"] == "partial"
    assert result["runtime_status"] == "success"
    assert {item["kind"] for item in result["findings"]} == {"observed", "derived"}
    assert result["root_cause_confirmed"] is False
    assert result["reasoning"] == {
        "status": "not_requested",
        "confirmed_cause_present": False,
        "summary": None,
        "assessment": None,
        "hypotheses": [],
        "recommended_next_checks": [],
        "limitations": [
            "backend_unavailable",
            "no_performance_baseline",
            "no_confirmed_run_cause",
        ],
    }
    assert result["measurements"][-1]["provenance"] == "configured"
    rendered = repr(result).casefold()
    for forbidden in (
        "prompt text",
        "model response",
        "tool arguments",
        "retrieved document",
        "backend url",
        "authorization",
        "trace_id",
    ):
        assert forbidden not in rendered


def test_failure_projection_keeps_existing_failure_evidence_without_cause_promotion() -> (
    None
):
    result = _call("failure", failed=True)

    assert result["runtime_status"] == "failed"
    assert [item["category"] for item in result["findings"]] == ["failure"]
    assert result["findings"][0]["kind"] == "observed"
    assert result["root_cause_confirmed"] is False
    assert "backend_unavailable" in result["limitations"]


def test_performance_projection_preserves_token_and_cost_provenance() -> None:
    result = _call("performance")

    measurements = result["measurements"]
    assert any(
        item["name"] == "total_tokens" and item["provenance"] == "observed"
        for item in measurements
    )
    assert any(
        item["name"] == "api_cost_usd"
        and item["provenance"] == "configured"
        and item["scope"] == "model_configuration"
        for item in measurements
    )
    assert all(
        item["name"] != "api_cost_usd"
        or item["value"] != 0.0
        or item["provenance"] == "configured"
        for item in measurements
    )


def test_inaccessible_run_is_neutral_and_does_not_expose_the_service_error() -> None:
    server = create_rca_mcp_server(
        analysis_service=_FakeAnalysisService(inaccessible=True)  # type: ignore[arg-type]
    )

    async def call() -> None:
        with pytest.raises(ToolError) as error:
            await server.call_tool("analyze_run", {"run_id": str(RUN_ID)})
        assert "hidden-classified-run" not in str(error.value)
        assert "not accessible" not in str(error.value).casefold()

    asyncio.run(call())


def test_reasoning_is_appended_without_changing_deterministic_projection() -> None:
    server = create_rca_mcp_server(
        analysis_service=_FakeAnalysisService(),  # type: ignore[arg-type]
        reasoner=_FakeReasoner(),
    )

    async def call() -> dict[str, object]:
        result = await server.call_tool(
            "analyze_run",
            {
                "run_id": str(RUN_ID),
                "focus": "overview",
                "reasoning": "explain",
            },
        )
        return result.structured_content

    result = asyncio.run(call())

    assert {item["kind"] for item in result["findings"]} == {"observed", "derived"}
    assert result["root_cause_confirmed"] is False
    assert result["reasoning"]["status"] == "available"
    assert result["reasoning"]["hypotheses"][0]["kind"] == "hypothesis"


def test_rls_failure_happens_before_optional_reasoning() -> None:
    reasoner = _FakeReasoner()
    server = create_rca_mcp_server(
        analysis_service=_FakeAnalysisService(inaccessible=True),  # type: ignore[arg-type]
        reasoner=reasoner,
    )

    async def call() -> None:
        with pytest.raises(ToolError):
            await server.call_tool(
                "analyze_run",
                {"run_id": str(RUN_ID), "reasoning": "explain"},
            )

    asyncio.run(call())

    assert reasoner.calls == 0


def _call(focus: str, *, failed: bool = False) -> dict[str, object]:
    server = create_rca_mcp_server(
        analysis_service=_FakeAnalysisService(failed=failed)  # type: ignore[arg-type]
    )

    async def call() -> dict[str, object]:
        result = await server.call_tool(
            "analyze_run", {"run_id": str(RUN_ID), "focus": focus}
        )
        return result.structured_content

    return asyncio.run(call())


async def _tools() -> list[object]:
    return [object()]


class _FakeAnalysisService:
    def __init__(self, *, failed: bool = False, inaccessible: bool = False) -> None:
        self._failed = failed
        self._inaccessible = inaccessible

    async def analyze(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RcaAnalysisReport:
        assert run_id == RUN_ID
        assert security_context.authenticated
        if self._inaccessible:
            raise RcaRunNotAccessibleError("hidden-classified-run")
        runtime_status = (
            RcaRuntimeStatus.FAILED if self._failed else RcaRuntimeStatus.SUCCESS
        )
        source_statuses = (
            RcaSourceAvailability(
                evidence_ref="EV-SOURCE-001",
                source=RcaEvidenceSource.RUNTIME,
                status=RcaEvidenceSourceStatus.AVAILABLE,
            ),
            RcaSourceAvailability(
                evidence_ref="EV-SOURCE-002",
                source=RcaEvidenceSource.TEMPO,
                status=RcaEvidenceSourceStatus.AVAILABLE,
            ),
            RcaSourceAvailability(
                evidence_ref="EV-SOURCE-003",
                source=RcaEvidenceSource.LOKI,
                status=RcaEvidenceSourceStatus.UNAVAILABLE,
                limitations=(RcaLimitationCode.BACKEND_UNAVAILABLE,),
            ),
            RcaSourceAvailability(
                evidence_ref="EV-SOURCE-004",
                source=RcaEvidenceSource.PROMETHEUS,
                status=RcaEvidenceSourceStatus.AVAILABLE,
            ),
            RcaSourceAvailability(
                evidence_ref="EV-SOURCE-005",
                source=RcaEvidenceSource.LANGFUSE,
                status=RcaEvidenceSourceStatus.AVAILABLE,
            ),
        )
        runtime = RcaRuntimeEvidence(
            evidence_ref="EV-RUNTIME-001",
            status=runtime_status,
            run_profile="INTERNAL_DIAGNOSTIC",
            model_profile="local_quality",
            created_at=NOW,
            updated_at=NOW,
            error_code="mcp_unavailable" if self._failed else None,
            tool_call_count=1,
        )
        findings = (
            RcaFinding(
                finding_id="F-OBSERVED-001",
                kind=RcaFindingKind.OBSERVED,
                category=RcaFindingCategory.FAILURE
                if self._failed
                else RcaFindingCategory.RUN_LIFECYCLE,
                severity=RcaSeverity.ERROR if self._failed else RcaSeverity.INFO,
                affected_component=RcaComponent.AGENT_RUNTIME,
                statement="Terminal runtime failure was recorded."
                if self._failed
                else "Run completed successfully.",
                confidence=RcaConfidence.HIGH,
                evidence_refs=("EV-RUNTIME-001",),
            ),
            RcaFinding(
                finding_id="F-DERIVED-002",
                kind=RcaFindingKind.DERIVED,
                category=RcaFindingCategory.LATENCY,
                severity=RcaSeverity.INFO,
                affected_component=RcaComponent.LLM,
                statement="Measured LLM timing contribution was recorded.",
                confidence=RcaConfidence.HIGH,
                evidence_refs=("EV-MEASUREMENT-001",),
            ),
        )
        measurements = (
            RcaMeasurement(
                evidence_ref="EV-MEASUREMENT-001",
                name=RcaMeasurementName.RUN_DURATION_MS,
                value=1200,
                unit=RcaMeasurementUnit.MILLISECONDS,
                provenance=RcaMeasurementProvenance.OBSERVED,
                scope=RcaMeasurementScope.RUN,
            ),
            RcaMeasurement(
                evidence_ref="EV-MEASUREMENT-002",
                name=RcaMeasurementName.TOTAL_TOKENS,
                value=42,
                unit=RcaMeasurementUnit.COUNT,
                provenance=RcaMeasurementProvenance.OBSERVED,
                scope=RcaMeasurementScope.RUN,
            ),
            RcaMeasurement(
                evidence_ref="EV-MEASUREMENT-003",
                name=RcaMeasurementName.API_COST_USD,
                value=0,
                unit=RcaMeasurementUnit.USD,
                provenance=RcaMeasurementProvenance.CONFIGURED,
                scope=RcaMeasurementScope.MODEL_CONFIGURATION,
            ),
        )
        evidence = RcaEvidenceBundle(
            run_id=RUN_ID,
            source_availability=source_statuses,
            runtime=runtime,
            measurements=measurements,
        )
        return RcaAnalysisReport(
            run_id=RUN_ID,
            analysis_status=RcaAnalysisStatus.PARTIAL,
            evidence=evidence,
            deterministic_findings=findings,
            overall_limitations=(
                RcaLimitationCode.BACKEND_UNAVAILABLE,
                RcaLimitationCode.NO_PERFORMANCE_BASELINE,
            ),
            completeness=RcaCompleteness(
                available_sources=(
                    RcaEvidenceSource.RUNTIME,
                    RcaEvidenceSource.TEMPO,
                    RcaEvidenceSource.PROMETHEUS,
                    RcaEvidenceSource.LANGFUSE,
                ),
                incomplete_sources=(RcaEvidenceSource.LOKI,),
                not_applicable_sources=(),
            ),
        )


class _FakeReasoner:
    def __init__(self) -> None:
        self.calls = 0

    def reason(
        self, report: RcaAnalysisReport, *, focus: RcaFocus
    ) -> RcaReasoningResult:
        self.calls += 1
        assert focus is RcaFocus.OVERVIEW
        return RcaReasoningResult(
            status=RcaReasoningStatus.AVAILABLE,
            confirmed_cause_present=False,
            summary="The run completed with measured LLM timing.",
            assessment=RcaReasoningAssessment.COMPLETED_WITHOUT_CONFIRMED_CAUSE,
            hypotheses=(
                {
                    "kind": "hypothesis",
                    "statement": "Further timing investigation may be useful.",
                    "confidence": "low",
                    "evidence_refs": ("EV-MEASUREMENT-001",),
                },
            ),
            limitations=report.overall_limitations,
        )
