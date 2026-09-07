"""Read-only MCP transport for deterministic, authorized RCA reports."""

from __future__ import annotations

import argparse
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from industrial_ai_agent.agent.model_egress import EgressCheckedLLMClient
from industrial_ai_agent.agent.model_routing import DeterministicModelRouter
from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.application.rca import (
    RcaAnalysisReport,
    RcaAnalysisStatus,
    RcaComponent,
    RcaConfidence,
    RcaEvidenceSource,
    RcaEvidenceSourceStatus,
    RcaFindingCategory,
    RcaFindingKind,
    RcaLimitationCode,
    RcaMeasurementName,
    RcaMeasurementProvenance,
    RcaMeasurementScope,
    RcaMeasurementUnit,
    RcaRuntimeStatus,
    RcaSeverity,
)
from industrial_ai_agent.application.rca_analysis import (
    DefaultDeterministicRcaAnalyzer,
    RcaAnalysisService,
    RcaEvidenceCollector,
)
from industrial_ai_agent.application.rca_evidence import (
    RcaRunNotAccessibleError,
    RcaRuntimeEvidenceUnavailableError,
)
from industrial_ai_agent.application.rca_reasoning import (
    LlmRcaReasoner,
    RcaFocus,
    RcaReasoner,
    RcaReasoningAssessment,
    RcaReasoningLimitation,
    RcaReasoningResult,
    RcaReasoningStatus,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    LLMConfiguration,
    load_llm_configuration,
    local_only_mode_enabled,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.mcp_access_control import (
    McpHttpAccessControl,
    create_demo_mcp_access_control,
    install_mcp_http_access_control,
)
from industrial_ai_agent.infrastructure.mcp_schema_validation import (
    require_strict_mcp_tool_arguments,
)
from industrial_ai_agent.infrastructure.observability_backends import (
    BackendConfiguration,
    LokiAdapter,
    ObservabilityEvidenceService,
    PrometheusAdapter,
    TempoAdapter,
)
from industrial_ai_agent.infrastructure.observed_llm_client import ObservedLLMClient
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.rca_evidence import (
    LangfuseRcaEvidenceAdapter,
    ObservabilityRcaEvidenceAdapter,
    StoreBackedRuntimeRcaEvidenceAdapter,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    configure_telemetry,
    run_instrumented_mcp_http_server,
    sanitized_error_code,
)

RCA_MCP_SERVER_NAME = "rca_mcp"
RCA_MCP_SERVER_VERSION = "0.1.0"
RCA_MCP_HTTP_PATH = "/mcp"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_CONFIGURATION_PATH = Path(
    os.getenv(
        "MODEL_CONFIGURATION_PATH",
        str(PROJECT_ROOT / "config" / "model_profiles.toml"),
    )
)

RunIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        ),
    ),
]
McpRcaFocus = Literal["overview", "failure", "performance"]
RcaReasoningMode = Literal["none", "explain"]

_RCA_TOOL_PERMISSIONS = {"analyze_run": McpPermission.READ_RCA}
_FAILURE_CATEGORIES = frozenset(
    {
        RcaFindingCategory.RUN_LIFECYCLE,
        RcaFindingCategory.FAILURE,
        RcaFindingCategory.MCP,
        RcaFindingCategory.RETRIEVAL,
        RcaFindingCategory.PERSISTENCE,
        RcaFindingCategory.APPROVAL,
        RcaFindingCategory.TELEMETRY,
    }
)
_PERFORMANCE_CATEGORIES = frozenset(
    {
        RcaFindingCategory.LATENCY,
        RcaFindingCategory.LLM,
        RcaFindingCategory.TOKEN_USAGE,
        RcaFindingCategory.COST,
        RcaFindingCategory.MCP,
        RcaFindingCategory.RETRIEVAL,
        RcaFindingCategory.PERSISTENCE,
        RcaFindingCategory.APPROVAL,
        RcaFindingCategory.TELEMETRY,
    }
)
_PERFORMANCE_MEASUREMENTS = frozenset(
    {
        RcaMeasurementName.RUN_DURATION_MS,
        RcaMeasurementName.COMPONENT_DURATION_MS,
        RcaMeasurementName.LATENCY_SHARE,
        RcaMeasurementName.INPUT_TOKENS,
        RcaMeasurementName.OUTPUT_TOKENS,
        RcaMeasurementName.TOTAL_TOKENS,
        RcaMeasurementName.API_COST_USD,
        RcaMeasurementName.APPROVAL_WAIT_MS,
        RcaMeasurementName.GENERATION_COUNT,
    }
)


class _McpModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _SourceStatusProjection(_McpModel):
    source: RcaEvidenceSource
    status: RcaEvidenceSourceStatus
    limitations: tuple[RcaLimitationCode, ...]


class _FindingProjection(_McpModel):
    finding_id: str
    kind: RcaFindingKind
    category: RcaFindingCategory
    severity: RcaSeverity
    affected_component: RcaComponent
    statement: str
    confidence: RcaConfidence
    evidence_refs: tuple[str, ...]


class _MeasurementProjection(_McpModel):
    name: RcaMeasurementName
    value: float = Field(ge=0)
    unit: RcaMeasurementUnit
    provenance: RcaMeasurementProvenance
    scope: RcaMeasurementScope


class _CompletenessProjection(_McpModel):
    available_sources: tuple[RcaEvidenceSource, ...]
    incomplete_sources: tuple[RcaEvidenceSource, ...]
    not_applicable_sources: tuple[RcaEvidenceSource, ...]


class _ReasoningHypothesisProjection(_McpModel):
    kind: Literal["hypothesis"]
    statement: str
    confidence: RcaConfidence
    evidence_refs: tuple[str, ...]


class _ReasoningProjection(_McpModel):
    status: RcaReasoningStatus
    confirmed_cause_present: bool
    summary: str | None
    assessment: RcaReasoningAssessment | None
    hypotheses: tuple[_ReasoningHypothesisProjection, ...]
    recommended_next_checks: tuple[str, ...]
    limitations: tuple[RcaLimitationCode | RcaReasoningLimitation, ...]


class _RcaReportProjection(_McpModel):
    run_id: UUID
    analysis_status: RcaAnalysisStatus
    runtime_status: RcaRuntimeStatus | None
    focus: RcaFocus
    completeness: _CompletenessProjection
    source_statuses: tuple[_SourceStatusProjection, ...]
    findings: tuple[_FindingProjection, ...]
    measurements: tuple[_MeasurementProjection, ...]
    limitations: tuple[RcaLimitationCode, ...]
    root_cause_confirmed: bool
    reasoning: _ReasoningProjection


def create_rca_mcp_server(
    *,
    analysis_service: RcaAnalysisService,
    reasoner: RcaReasoner | None = None,
    access_control: McpHttpAccessControl | None = None,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Expose one bounded projection over the existing deterministic RCA service."""
    server = MCPServer(
        name=RCA_MCP_SERVER_NAME,
        version=RCA_MCP_SERVER_VERSION,
        description="Read-only deterministic RCA for one RLS-authorized agent run.",
    )

    @server.tool(
        name="analyze_run",
        description=(
            "Analyze one authorized run with deterministic RCA. "
            "Use this first for a general run analysis; use lower-level MCP evidence "
            "only for targeted follow-up."
        ),
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def analyze_run(
        run_id: RunIdentifier,
        focus: McpRcaFocus = "overview",
        reasoning: RcaReasoningMode = "none",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        access_context = _authorize(ctx, access_control, "analyze_run")
        try:
            report = await _invoke_analysis(
                telemetry,
                run_id,
                lambda: analysis_service.analyze(
                    UUID(run_id), access_context.security_context
                ),
            )
        except RcaRunNotAccessibleError as error:
            # RLS deliberately makes missing and inaccessible runs indistinguishable.
            raise LookupError(
                "RCA analysis is unavailable for the requested run"
            ) from error
        except RcaRuntimeEvidenceUnavailableError as error:
            raise RuntimeError("RCA runtime evidence is unavailable") from error
        focus_value = RcaFocus(focus)
        reasoning_result = _reasoning_result(
            report,
            focus=focus_value,
            requested=reasoning == "explain",
            reasoner=reasoner,
            telemetry=telemetry,
        )
        return _project_report(report, focus_value, reasoning_result).model_dump(
            mode="json"
        )

    require_strict_mcp_tool_arguments(server, "analyze_run")
    if access_control is not None:
        install_mcp_http_access_control(server, access_control)
    return server


def create_secure_rca_mcp_server(*, telemetry: Telemetry | None = None) -> MCPServer:
    """Compose RCA directly from existing application ports and infrastructure adapters."""
    database_url = os.getenv("AGENT_RUNTIME_DATABASE_URL") or os.getenv(
        "FACTORY_DATABASE_URL"
    )
    if not database_url:
        raise RuntimeError(
            "AGENT_RUNTIME_DATABASE_URL or FACTORY_DATABASE_URL is required"
        )
    session_factory = PostgreSqlSessionFactory(database_url)
    observability = _create_observability_evidence_service(
        BackendConfiguration(
            tempo_url=os.getenv("TEMPO_URL", "http://tempo:3200"),
            loki_url=os.getenv("LOKI_URL", "http://loki:3100"),
            prometheus_url=os.getenv("PROMETHEUS_URL", "http://prometheus:9090"),
            timeout_seconds=float(
                os.getenv("OBSERVABILITY_BACKEND_TIMEOUT_SECONDS", "2")
            ),
        )
    )
    observability_adapter = ObservabilityRcaEvidenceAdapter(observability)
    collector = RcaEvidenceCollector(
        runtime=StoreBackedRuntimeRcaEvidenceAdapter(
            lambda context: PostgreSqlAgentRunStore(session_factory, context)
        ),
        trace=observability_adapter,
        logs=observability_adapter,
        metrics=observability_adapter,
        llm=_create_langfuse_evidence_adapter(),
    )
    analysis_service = RcaAnalysisService(collector, DefaultDeterministicRcaAnalyzer())
    reasoner = _create_rca_reasoner(telemetry)
    server: MCPServer

    async def listed_tools() -> list[Any]:
        return await server.list_tools()

    access_control = create_demo_mcp_access_control(
        tools=listed_tools,
        required_permission=lambda tool_name: _RCA_TOOL_PERMISSIONS[tool_name],
    )
    server = create_rca_mcp_server(
        analysis_service=analysis_service,
        reasoner=reasoner,
        access_control=access_control,
        telemetry=telemetry,
    )
    return server


def _create_observability_evidence_service(
    configuration: BackendConfiguration,
) -> ObservabilityEvidenceService:
    timeout = httpx.Timeout(configuration.timeout_seconds)
    return ObservabilityEvidenceService(
        tempo=TempoAdapter(
            configuration.tempo_url, client=httpx.Client(timeout=timeout)
        ),
        loki=LokiAdapter(configuration.loki_url, client=httpx.Client(timeout=timeout)),
        prometheus=PrometheusAdapter(
            configuration.prometheus_url, client=httpx.Client(timeout=timeout)
        ),
    )


def _create_langfuse_evidence_adapter() -> LangfuseRcaEvidenceAdapter | None:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=os.getenv("LANGFUSE_BASE_URL", "http://langfuse-web:3000"),
            timeout=2,
            tracing_enabled=False,
        )
        return LangfuseRcaEvidenceAdapter(client.api.observations)
    except Exception:  # noqa: BLE001 - Langfuse remains an isolated optional source.
        return None


def _create_rca_reasoner(telemetry: Telemetry | None) -> RcaReasoner | None:
    """Compose the optional reasoner through the established routing/egress boundary."""
    try:
        configuration = load_llm_configuration(DEFAULT_MODEL_CONFIGURATION_PATH)
    except (OSError, ValueError):
        return None
    adapter = OpenAICompatibleLLMClient(configuration)
    return LlmRcaReasoner(
        router=DeterministicModelRouter(),
        profiles=configuration.get_routing_profiles(
            local_only=local_only_mode_enabled()
        ),
        timeout_seconds=float(os.getenv("RCA_REASONING_TIMEOUT_SECONDS", "90")),
        client_factory=lambda classification, focus: _reasoning_llm_client(
            adapter,
            configuration=configuration,
            classification=classification,
            focus=focus,
            telemetry=telemetry,
        ),
    )


def _reasoning_llm_client(
    adapter: OpenAICompatibleLLMClient,
    *,
    configuration: LLMConfiguration,
    classification: DataClassification,
    focus: RcaFocus,
    telemetry: Telemetry | None,
):
    checked = EgressCheckedLLMClient(adapter, configuration, classification)
    if telemetry is None:
        return checked
    return ObservedLLMClient(
        checked,
        configuration=configuration,
        data_classification=classification,
        telemetry=telemetry,
        operation_type="rca.reasoning",
        rca_focus=focus.value,
    )


def _reasoning_result(
    report: RcaAnalysisReport,
    *,
    focus: RcaFocus,
    requested: bool,
    reasoner: RcaReasoner | None,
    telemetry: Telemetry | None,
) -> RcaReasoningResult:
    if not requested:
        return RcaReasoningResult.unavailable(RcaReasoningStatus.NOT_REQUESTED, report)
    if reasoner is None:
        return RcaReasoningResult.unavailable(RcaReasoningStatus.UNAVAILABLE, report)
    try:
        if telemetry is None:
            return reasoner.reason(report, focus=focus)
        with telemetry.span(
            "rca.reasoning",
            {
                "run.id": str(report.run_id),
                "operation.type": "rca.reasoning",
                "rca.focus": focus.value,
            },
        ):
            return reasoner.reason(report, focus=focus)
    except Exception:  # noqa: BLE001 - reasoning is optional and failure-isolated.
        return RcaReasoningResult.unavailable(RcaReasoningStatus.UNAVAILABLE, report)


def _authorize(
    ctx: Context | None,
    access_control: McpHttpAccessControl | None,
    tool_name: str,
):
    if access_control is None:
        return type(
            "LocalAccess",
            (),
            {
                "security_context": SecurityContext(
                    subject_id="rca-mcp-stdio",
                    roles=("rca-mcp-stdio",),
                    clearance=DataClassification.CONFIDENTIAL,
                    authenticated=True,
                )
            },
        )()
    if ctx is None:
        raise PermissionError("MCP authentication failed")
    access_context = access_control.access_context_from_headers(ctx.headers)
    access_control.authorize_tool(access_context, tool_name)
    return access_context


async def _invoke_analysis(
    telemetry: Telemetry | None,
    run_id: str,
    action: Callable[[], Awaitable[RcaAnalysisReport]],
) -> RcaAnalysisReport:
    if telemetry is None:
        return await action()
    started = perf_counter()
    status = "success"
    attributes = {
        "mcp.tool": "analyze_run",
        "mcp.operation": "read",
        "operation.type": "read",
    }
    try:
        with (
            telemetry.span("rca.mcp.tool", attributes),
            telemetry.span("rca.analysis", {"run.id": run_id}),
        ):
            result = await action()
        telemetry.log_event(event="mcp.server.completed", run_id=run_id)
        return result
    except BaseException as error:
        status = "failure"
        telemetry.log_error(
            event="mcp.server.failed",
            run_id=run_id,
            error_code=sanitized_error_code(error),
        )
        raise
    finally:
        telemetry.record_mcp_call(
            attributes={**attributes, "operation.status": status},
            duration_seconds=perf_counter() - started,
        )


def _project_report(
    report: RcaAnalysisReport,
    focus: RcaFocus,
    reasoning: RcaReasoningResult,
) -> _RcaReportProjection:
    findings = report.deterministic_findings
    measurements = report.evidence.measurements
    if focus == "failure":
        findings = tuple(
            finding for finding in findings if finding.category in _FAILURE_CATEGORIES
        )
        measurements = tuple(
            measurement
            for measurement in measurements
            if measurement.name is RcaMeasurementName.RUN_DURATION_MS
        )
    elif focus == "performance":
        findings = tuple(
            finding
            for finding in findings
            if finding.category in _PERFORMANCE_CATEGORIES
        )
        measurements = tuple(
            measurement
            for measurement in measurements
            if measurement.name in _PERFORMANCE_MEASUREMENTS
        )
    return _RcaReportProjection(
        run_id=report.run_id,
        analysis_status=report.analysis_status,
        runtime_status=(
            report.evidence.runtime.status if report.evidence.runtime else None
        ),
        focus=focus,
        completeness=_CompletenessProjection(
            available_sources=report.completeness.available_sources,
            incomplete_sources=report.completeness.incomplete_sources,
            not_applicable_sources=report.completeness.not_applicable_sources,
        ),
        source_statuses=tuple(
            _SourceStatusProjection(
                source=item.source,
                status=item.status,
                limitations=item.limitations,
            )
            for item in report.evidence.source_availability
        ),
        findings=tuple(
            _FindingProjection(
                finding_id=finding.finding_id,
                kind=finding.kind,
                category=finding.category,
                severity=finding.severity,
                affected_component=finding.affected_component,
                statement=finding.statement,
                confidence=finding.confidence,
                evidence_refs=finding.evidence_refs,
            )
            for finding in findings
        ),
        measurements=tuple(
            _MeasurementProjection(
                name=measurement.name,
                value=measurement.value,
                unit=measurement.unit,
                provenance=measurement.provenance,
                scope=measurement.scope,
            )
            for measurement in measurements
        ),
        limitations=report.overall_limitations,
        root_cause_confirmed=any(
            finding.kind is RcaFindingKind.CONFIRMED_RUN_CAUSE
            for finding in report.deterministic_findings
        ),
        reasoning=_project_reasoning(reasoning),
    )


def _project_reasoning(reasoning: RcaReasoningResult) -> _ReasoningProjection:
    return _ReasoningProjection(
        status=reasoning.status,
        confirmed_cause_present=reasoning.confirmed_cause_present,
        summary=reasoning.summary,
        assessment=reasoning.assessment,
        hypotheses=tuple(
            _ReasoningHypothesisProjection(
                kind=hypothesis.kind,
                statement=hypothesis.statement,
                confidence=hypothesis.confidence,
                evidence_refs=hypothesis.evidence_refs,
            )
            for hypothesis in reasoning.hypotheses
        ),
        recommended_next_checks=reasoning.recommended_next_checks,
        limitations=reasoning.limitations,
    )


def main() -> None:
    """Run the independent authenticated Streamable HTTP RCA MCP service."""
    args = _parse_args()
    if args.transport == "stdio":
        raise RuntimeError(
            "RCA MCP stdio composition requires an explicit analysis service"
        )
    telemetry = _create_telemetry()
    server = create_secure_rca_mcp_server(telemetry=telemetry)
    run_instrumented_mcp_http_server(
        server,
        host=args.host,
        port=args.port,
        streamable_http_path=RCA_MCP_HTTP_PATH,
        telemetry=telemetry,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the read-only RCA MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("RCA_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("RCA_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("RCA_MCP_PORT", "8005"))
    )
    return parser.parse_args()


def _create_telemetry() -> Telemetry:
    return configure_telemetry(
        TelemetryConfiguration(
            enabled=os.getenv("OTEL_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "127.0.0.1:4317"),
            service_name=os.getenv("OTEL_SERVICE_NAME", "rca-mcp"),
            langfuse_enabled=os.getenv("LANGFUSE_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            langfuse_base_url=os.getenv(
                "LANGFUSE_BASE_URL", "http://langfuse-web:3000"
            ),
            langfuse_environment=os.getenv("LANGFUSE_ENVIRONMENT", "local"),
        )
    )


if __name__ == "__main__":
    main()
