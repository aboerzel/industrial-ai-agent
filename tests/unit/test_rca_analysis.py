import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from industrial_ai_agent.application.rca import (
    RcaAnalysisStatus,
    RcaApprovalState,
    RcaComponent,
    RcaEvidenceSource,
    RcaEvidenceSourceStatus,
    RcaFindingCategory,
    RcaFindingKind,
    RcaMeasurementName,
    RcaMeasurementUnit,
    RcaOperation,
    RcaOperationStatus,
    RcaRuntimeStatus,
    RcaSeverity,
)
from industrial_ai_agent.application.rca_analysis import (
    DefaultDeterministicRcaAnalyzer,
    RcaAnalysisService,
    RcaEvidenceCollector,
)
from industrial_ai_agent.application.rca_evidence import (
    RcaEvidenceMalformedError,
    RcaEvidenceUnavailableError,
    RcaLogObservation,
    RcaMetricObservation,
    RcaRunNotAccessibleError,
    RcaRuntimeEvidenceUnavailableError,
    RcaRuntimeObservation,
    RcaSpanObservation,
    RcaToolTrajectoryObservation,
    RcaTraceObservation,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
TRACE_ID = "0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 6, tzinfo=UTC)
CONTEXT = SecurityContext(
    subject_id="rca-test",
    roles=("engineer",),
    clearance=DataClassification.INTERNAL,
    authenticated=True,
)


class FakeRuntimeEvidence:
    def __init__(
        self,
        *,
        runtime: RcaRuntimeObservation | None = None,
        tools: tuple[RcaToolTrajectoryObservation, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.runtime = runtime or _runtime()
        self.tools = tools
        self.error = error
        self.trajectory_requested = False

    async def inspect_run(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RcaRuntimeObservation:
        if self.error is not None:
            raise self.error
        return self.runtime

    async def get_tool_trajectory(
        self, run_id: UUID, security_context: SecurityContext
    ) -> tuple[RcaToolTrajectoryObservation, ...]:
        self.trajectory_requested = True
        return self.tools


class FakeTraceEvidence:
    def __init__(
        self, trace: RcaTraceObservation | None = None, error: Exception | None = None
    ) -> None:
        self.trace = trace or _trace()
        self.error = error
        self.requested = False

    def get_run_trace(self, run_id: UUID) -> RcaTraceObservation:
        self.requested = True
        if self.error is not None:
            raise self.error
        return self.trace


class FakeLogEvidence:
    def __init__(
        self,
        logs: tuple[RcaLogObservation, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.logs = logs if logs is not None else (_log(),)
        self.error = error

    def get_trace_logs(
        self, trace: RcaTraceObservation
    ) -> tuple[RcaLogObservation, ...]:
        if self.error is not None:
            raise self.error
        return self.logs


class FakeMetricEvidence:
    def __init__(
        self,
        metrics: tuple[RcaMetricObservation, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.metrics = metrics if metrics is not None else (_metric(),)
        self.error = error

    def get_trace_metrics(
        self, trace: RcaTraceObservation
    ) -> tuple[RcaMetricObservation, ...]:
        if self.error is not None:
            raise self.error
        return self.metrics


def test_collector_projects_all_safe_sources_with_stable_unique_references() -> None:
    bundle = _collect()

    assert [source.status for source in bundle.source_availability] == [
        RcaEvidenceSourceStatus.AVAILABLE,
        RcaEvidenceSourceStatus.AVAILABLE,
        RcaEvidenceSourceStatus.AVAILABLE,
        RcaEvidenceSourceStatus.AVAILABLE,
        RcaEvidenceSourceStatus.NOT_APPLICABLE,
    ]
    references = bundle.evidence_references()
    assert len(references) == len(set(references))
    serialized = bundle.model_dump_json()
    for forbidden in (
        "prompt",
        "model_response",
        "tool_arguments",
        "tool_results",
        "retrieved_text",
        "raw_log",
        "sql",
        "credential",
        "url",
        "backend_attributes",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("source", ["tempo", "loki", "prometheus"])
def test_collector_isolates_unavailable_non_runtime_sources(source: str) -> None:
    trace = FakeTraceEvidence(
        error=RcaEvidenceUnavailableError("tempo down") if source == "tempo" else None
    )
    logs = FakeLogEvidence(
        error=RcaEvidenceUnavailableError("loki down") if source == "loki" else None
    )
    metrics = FakeMetricEvidence(
        error=RcaEvidenceUnavailableError("prometheus down")
        if source == "prometheus"
        else None
    )

    report = _report(trace=trace, logs=logs, metrics=metrics)

    assert report.analysis_status is RcaAnalysisStatus.PARTIAL
    status_by_source = {
        item.source: item.status for item in report.evidence.source_availability
    }
    expected = {
        "tempo": RcaEvidenceSourceStatus.UNAVAILABLE,
        "loki": RcaEvidenceSourceStatus.UNAVAILABLE,
        "prometheus": RcaEvidenceSourceStatus.UNAVAILABLE,
    }[source]
    source_key = RcaEvidenceSource(source)
    assert status_by_source[source_key] is expected
    assert report.evidence.runtime is not None


def test_collector_marks_malformed_source_without_discarding_other_evidence() -> None:
    bundle = _collect(
        logs=FakeLogEvidence(error=RcaEvidenceMalformedError("bad response"))
    )

    status_by_source = {item.source: item.status for item in bundle.source_availability}
    assert status_by_source[RcaEvidenceSource.LOKI] is RcaEvidenceSourceStatus.MALFORMED
    assert (
        status_by_source[RcaEvidenceSource.TEMPO] is RcaEvidenceSourceStatus.AVAILABLE
    )
    assert (
        status_by_source[RcaEvidenceSource.PROMETHEUS]
        is RcaEvidenceSourceStatus.AVAILABLE
    )


def test_collector_fails_closed_before_telemetry_when_run_is_not_authorized() -> None:
    trace = FakeTraceEvidence()
    runtime = FakeRuntimeEvidence(error=RcaRunNotAccessibleError("denied"))

    with pytest.raises(RcaRunNotAccessibleError):
        _collect(runtime=runtime, trace=trace)

    assert not trace.requested
    assert not runtime.trajectory_requested


def test_runtime_evidence_outage_is_a_safe_service_failure() -> None:
    runtime = FakeRuntimeEvidence(error=RcaRuntimeEvidenceUnavailableError("down"))

    with pytest.raises(RcaRuntimeEvidenceUnavailableError):
        _collect(runtime=runtime)


def test_successful_run_without_error_has_no_hypothesis_or_confirmed_cause() -> None:
    findings = DefaultDeterministicRcaAnalyzer().analyze(_collect())

    assert not [
        finding
        for finding in findings
        if finding.category is RcaFindingCategory.FAILURE
    ]
    assert all(finding.kind is not RcaFindingKind.HYPOTHESIS for finding in findings)
    assert all(
        finding.kind is not RcaFindingKind.CONFIRMED_RUN_CAUSE for finding in findings
    )


def test_analyzer_reports_terminal_runtime_failure_as_observed() -> None:
    bundle = _collect(
        runtime=FakeRuntimeEvidence(
            runtime=_runtime(status=RcaRuntimeStatus.FAILED, error_code="RUN_FAILED")
        )
    )

    finding = DefaultDeterministicRcaAnalyzer().analyze(bundle)[0]

    assert finding.kind is RcaFindingKind.OBSERVED
    assert finding.category is RcaFindingCategory.RUN_LIFECYCLE
    assert "RUN_FAILED" in finding.statement


@pytest.mark.parametrize(
    ("operation", "category", "expected_statement"),
    [
        (
            RcaOperation.MCP_DISCOVERY,
            RcaFindingCategory.MCP,
            "discovery boundary failed",
        ),
        (
            RcaOperation.MCP_TOOL,
            RcaFindingCategory.MCP,
            "tool execution boundary failed",
        ),
        (
            RcaOperation.RETRIEVAL_RERANK,
            RcaFindingCategory.RETRIEVAL,
            "retrieval retrieval.rerank stage failed",
        ),
    ],
)
def test_analyzer_derives_bounded_failed_operation_findings(
    operation: RcaOperation, category: RcaFindingCategory, expected_statement: str
) -> None:
    bundle = _collect(
        trace=FakeTraceEvidence(
            _trace(_span(operation, status=RcaOperationStatus.ERROR))
        )
    )

    findings = DefaultDeterministicRcaAnalyzer().analyze(bundle)

    assert any(
        finding.kind is RcaFindingKind.DERIVED
        and finding.category is category
        and expected_statement in finding.statement
        for finding in findings
    )
    assert all(
        finding.kind is not RcaFindingKind.CONFIRMED_RUN_CAUSE for finding in findings
    )


def test_analyzer_detects_repeated_mcp_tool_calls_without_claiming_unnecessary_work() -> (
    None
):
    runtime = FakeRuntimeEvidence(
        tools=(
            RcaToolTrajectoryObservation(
                1, "get_machine_status", RcaComponent.FACTORY_MCP
            ),
            RcaToolTrajectoryObservation(
                2, "get_machine_status", RcaComponent.FACTORY_MCP
            ),
        )
    )
    findings = DefaultDeterministicRcaAnalyzer().analyze(_collect(runtime=runtime))

    repeated = next(
        finding for finding in findings if "called 2 times" in finding.statement
    )
    assert repeated.kind is RcaFindingKind.DERIVED
    assert "unnecessary" not in repeated.statement.lower()


@pytest.mark.parametrize(
    ("dominant_operation", "component"),
    [
        (RcaOperation.LLM_CALL, RcaComponent.LLM),
        (RcaOperation.RETRIEVAL_SEARCH, RcaComponent.RETRIEVAL),
    ],
)
def test_analyzer_reports_largest_measured_component_without_claiming_cause(
    dominant_operation: RcaOperation, component: RcaComponent
) -> None:
    trace = _trace(
        _span(RcaOperation.AGENT_RUN, duration_ms=1_000),
        _span(dominant_operation, duration_ms=700),
        _span(RcaOperation.MCP_TOOL, duration_ms=100),
    )
    findings = DefaultDeterministicRcaAnalyzer().analyze(
        _collect(trace=FakeTraceEvidence(trace))
    )

    dominant = next(
        finding for finding in findings if "largest measured share" in finding.statement
    )
    assert dominant.affected_component is component
    assert "caused" not in dominant.statement


def test_nested_timing_partitions_root_intervals_without_double_counting() -> None:
    trace = _trace(
        _span(RcaOperation.AGENT_RUN, duration_ms=1_000),
        _span(RcaOperation.MCP_TOOL, duration_ms=800),
        _span(RcaOperation.RETRIEVAL_SEARCH, duration_ms=500),
        _span(RcaOperation.RETRIEVAL_RERANK, duration_ms=250),
    )
    findings = DefaultDeterministicRcaAnalyzer().analyze(
        _collect(trace=FakeTraceEvidence(trace))
    )

    duration_findings = [
        finding
        for finding in findings
        if any(
            measurement.name is RcaMeasurementName.COMPONENT_DURATION_MS
            for measurement in finding.measurements
        )
    ]
    total = sum(
        next(
            measurement.value
            for measurement in finding.measurements
            if measurement.name is RcaMeasurementName.COMPONENT_DURATION_MS
        )
        for finding in duration_findings
    )
    assert total <= 1_000
    assert any(
        finding.affected_component is RcaComponent.RETRIEVAL
        for finding in duration_findings
    )


def test_approval_wait_from_runtime_timing_is_part_of_timing_accounting() -> None:
    runtime = replace(
        _runtime(),
        approval_state=RcaApprovalState.APPROVED,
        approval_requested_at=NOW,
        approval_decided_at=NOW + timedelta(milliseconds=50),
    )
    trace = _trace(_span(RcaOperation.AGENT_RUN, duration_ms=100))

    findings = DefaultDeterministicRcaAnalyzer().analyze(
        _collect(
            runtime=FakeRuntimeEvidence(runtime=runtime), trace=FakeTraceEvidence(trace)
        )
    )

    approval = next(
        finding
        for finding in findings
        if finding.affected_component is RcaComponent.APPROVAL
        and any(
            measurement.name is RcaMeasurementName.COMPONENT_DURATION_MS
            for measurement in finding.measurements
        )
    )
    assert approval.measurements[0].value == 50


def test_incomplete_evidence_creates_explicit_telemetry_limitation() -> None:
    findings = DefaultDeterministicRcaAnalyzer().analyze(
        _collect(logs=FakeLogEvidence(error=RcaEvidenceUnavailableError("down")))
    )

    assert any(finding.category is RcaFindingCategory.TELEMETRY for finding in findings)


def test_truncated_trace_returns_partial_report_without_timing_conclusions() -> None:
    trace = RcaTraceObservation(TRACE_ID, (_span(RcaOperation.AGENT_RUN),), True)

    report = _report(trace=FakeTraceEvidence(trace))

    assert report.analysis_status is RcaAnalysisStatus.PARTIAL
    assert any(
        "trace was truncated" in finding.statement
        for finding in report.deterministic_findings
    )
    assert not any(
        finding.category is RcaFindingCategory.LATENCY
        for finding in report.deterministic_findings
    )


def test_analysis_service_returns_complete_partial_and_insufficient_reports() -> None:
    assert _report().analysis_status is RcaAnalysisStatus.COMPLETE
    assert (
        _report(
            logs=FakeLogEvidence(error=RcaEvidenceUnavailableError("down"))
        ).analysis_status
        is RcaAnalysisStatus.PARTIAL
    )
    assert (
        _report(
            trace=FakeTraceEvidence(error=RcaEvidenceUnavailableError("down"))
        ).analysis_status
        is RcaAnalysisStatus.PARTIAL
    )
    assert (
        _report(
            trace=FakeTraceEvidence(RcaTraceObservation(TRACE_ID, (), False))
        ).analysis_status
        is RcaAnalysisStatus.INSUFFICIENT_EVIDENCE
    )


def _collect(
    *,
    runtime: FakeRuntimeEvidence | None = None,
    trace: FakeTraceEvidence | None = None,
    logs: FakeLogEvidence | None = None,
    metrics: FakeMetricEvidence | None = None,
):
    return asyncio.run(
        RcaEvidenceCollector(
            runtime=runtime or FakeRuntimeEvidence(),
            trace=trace or FakeTraceEvidence(),
            logs=logs or FakeLogEvidence(),
            metrics=metrics or FakeMetricEvidence(),
        ).collect(RUN_ID, CONTEXT)
    )


def _report(
    **kwargs: FakeRuntimeEvidence
    | FakeTraceEvidence
    | FakeLogEvidence
    | FakeMetricEvidence,
):
    collector = RcaEvidenceCollector(
        runtime=kwargs.get("runtime", FakeRuntimeEvidence()),
        trace=kwargs.get("trace", FakeTraceEvidence()),
        logs=kwargs.get("logs", FakeLogEvidence()),
        metrics=kwargs.get("metrics", FakeMetricEvidence()),
    )
    return asyncio.run(
        RcaAnalysisService(collector, DefaultDeterministicRcaAnalyzer()).analyze(
            RUN_ID, CONTEXT
        )
    )


def _runtime(
    *,
    status: RcaRuntimeStatus = RcaRuntimeStatus.SUCCESS,
    error_code: str | None = None,
) -> RcaRuntimeObservation:
    return RcaRuntimeObservation(
        run_id=RUN_ID,
        status=status,
        data_classification=DataClassification.INTERNAL,
        run_profile="INTERNAL_DIAGNOSTIC",
        model_profile="troubleshooting",
        created_at=NOW,
        updated_at=NOW,
        error_code=error_code,
        tool_call_count=0,
        approval_state=RcaApprovalState.NONE,
        approval_requested_at=None,
        approval_decided_at=None,
    )


def _trace(*spans: RcaSpanObservation) -> RcaTraceObservation:
    return RcaTraceObservation(
        TRACE_ID, spans or (_span(RcaOperation.AGENT_RUN),), False
    )


def _span(
    operation: RcaOperation,
    *,
    status: RcaOperationStatus = RcaOperationStatus.OK,
    duration_ms: float = 100,
) -> RcaSpanObservation:
    return RcaSpanObservation(
        span_id=f"{len(operation.value):016x}",
        parent_span_id=None,
        operation=operation,
        component=RcaComponent.AGENT_RUNTIME,
        service=RcaComponent.AGENT_RUNTIME,
        started_at=NOW,
        duration_ms=duration_ms,
        status=status,
        error_type=None,
        error_code="OBSERVED_ERROR" if status is RcaOperationStatus.ERROR else None,
        safe_attributes=(),
    )


def _log() -> RcaLogObservation:
    return RcaLogObservation(
        NOW, RcaComponent.AGENT_RUNTIME, "run_completed", RcaSeverity.INFO, None
    )


def _metric() -> RcaMetricObservation:
    return RcaMetricObservation("run_count", 1, RcaMeasurementUnit.COUNT, NOW, NOW)
