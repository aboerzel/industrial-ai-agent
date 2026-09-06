from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from industrial_ai_agent.application.rca import (
    RcaAnalysisReport,
    RcaAnalysisStatus,
    RcaApprovalEvidence,
    RcaApprovalState,
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
    RcaLlmEvidence,
    RcaMeasurement,
    RcaMeasurementName,
    RcaMeasurementProvenance,
    RcaMeasurementScope,
    RcaMeasurementUnit,
    RcaOperationStatus,
    RcaRuntimeEvidence,
    RcaRuntimeStatus,
    RcaSeverity,
    RcaSourceAvailability,
)
from industrial_ai_agent.domain.security import DataClassification

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
TRACE_ID = "0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 6, tzinfo=UTC)


def test_valid_bundle_preserves_safe_evidence_and_classification() -> None:
    bundle = _bundle()

    assert bundle.run_id == RUN_ID
    assert bundle.trace_id == TRACE_ID
    assert bundle.data_classification is DataClassification.INTERNAL
    assert bundle.evidence_references() == {
        "EV-SOURCE-001",
        "EV-SOURCE-002",
        "EV-SOURCE-003",
        "EV-SOURCE-004",
        "EV-SOURCE-005",
        "EV-RUNTIME-001",
        "EV-LLM-001",
        "EV-MEASUREMENT-001",
        "EV-APPROVAL-001",
    }


def test_source_statuses_represent_each_source_independently() -> None:
    statuses = _source_availability(langfuse=RcaEvidenceSourceStatus.MISSING)
    bundle = _bundle(source_availability=statuses)

    assert bundle.source_availability[-1].source is RcaEvidenceSource.LANGFUSE
    assert bundle.source_availability[-1].status is RcaEvidenceSourceStatus.MISSING

    with pytest.raises(
        ValidationError, match="represent each RCA evidence source once"
    ):
        _bundle(source_availability=statuses[:-1])


def test_report_rejects_finding_reference_not_in_its_evidence_bundle() -> None:
    finding = _finding(evidence_refs=("EV-TRACE-999",))

    with pytest.raises(ValidationError, match="only evidence in this report"):
        _report(_bundle(), RcaAnalysisStatus.COMPLETE, findings=(finding,))


def test_partial_and_insufficient_reports_are_valid_supported_states() -> None:
    partial_bundle = _bundle(
        source_availability=_source_availability(
            loki=RcaEvidenceSourceStatus.UNAVAILABLE
        )
    )
    partial = _report(partial_bundle, RcaAnalysisStatus.PARTIAL)
    insufficient = _report(
        _bundle(
            source_availability=_source_availability(
                runtime=RcaEvidenceSourceStatus.MISSING,
                tempo=RcaEvidenceSourceStatus.UNAVAILABLE,
                loki=RcaEvidenceSourceStatus.UNAVAILABLE,
                prometheus=RcaEvidenceSourceStatus.NOT_APPLICABLE,
                langfuse=RcaEvidenceSourceStatus.MISSING,
            )
        ),
        RcaAnalysisStatus.INSUFFICIENT_EVIDENCE,
    )

    assert partial.completeness.incomplete_sources == (RcaEvidenceSource.LOKI,)
    assert insufficient.analysis_status is RcaAnalysisStatus.INSUFFICIENT_EVIDENCE


def test_complete_report_allows_a_source_that_is_not_applicable() -> None:
    report = _report(
        _bundle(
            source_availability=_source_availability(
                langfuse=RcaEvidenceSourceStatus.NOT_APPLICABLE
            )
        ),
        RcaAnalysisStatus.COMPLETE,
    )

    assert report.completeness.not_applicable_sources == (RcaEvidenceSource.LANGFUSE,)


def test_measurement_provenance_prevents_configured_cost_from_claiming_run_scope() -> (
    None
):
    configured = RcaMeasurement(
        evidence_ref="EV-MEASUREMENT-002",
        name=RcaMeasurementName.API_COST_USD,
        value=0,
        unit=RcaMeasurementUnit.USD,
        provenance=RcaMeasurementProvenance.CONFIGURED,
        scope=RcaMeasurementScope.MODEL_CONFIGURATION,
    )

    assert configured.provenance is RcaMeasurementProvenance.CONFIGURED
    with pytest.raises(ValidationError, match="model configuration"):
        RcaMeasurement(
            evidence_ref="EV-MEASUREMENT-003",
            name=RcaMeasurementName.API_COST_USD,
            value=0,
            unit=RcaMeasurementUnit.USD,
            provenance=RcaMeasurementProvenance.CONFIGURED,
            scope=RcaMeasurementScope.RUN,
        )


def test_bounded_enums_and_identifiers_reject_unknown_values() -> None:
    with pytest.raises(ValidationError):
        RcaLlmEvidence(
            evidence_ref="EV-LLM-001",
            provider="ollama",
            model_name="qwen3.5:9b",
            status="unknown",
            duration_ms=1,
        )
    with pytest.raises(ValidationError):
        _bundle(trace_id="not-a-trace")
    with pytest.raises(ValidationError):
        RcaSourceAvailability(
            evidence_ref="not-an-evidence-reference",
            source=RcaEvidenceSource.RUNTIME,
            status="timed_out",
        )
    with pytest.raises(ValidationError):
        _finding(kind="root_cause")


def test_serialized_contract_contains_no_raw_backend_payload_fields() -> None:
    rendered = str(
        _report(_bundle(), RcaAnalysisStatus.COMPLETE).model_dump(mode="json")
    ).casefold()

    for forbidden in (
        "prompt",
        "response",
        "arguments",
        "tool_result",
        "document",
        "raw_log",
        "sql",
        "credential",
        "url",
        "promql",
        "logql",
        "traceql",
    ):
        assert forbidden not in rendered


def test_confirmed_cause_is_closed_to_its_enum_value() -> None:
    confirmed = _finding(kind=RcaFindingKind.CONFIRMED_RUN_CAUSE)

    assert confirmed.kind is RcaFindingKind.CONFIRMED_RUN_CAUSE
    with pytest.raises(ValidationError):
        _finding(kind="confirmed_by_llm")


def _bundle(
    *,
    trace_id: str = TRACE_ID,
    source_availability: tuple[RcaSourceAvailability, ...] | None = None,
) -> RcaEvidenceBundle:
    return RcaEvidenceBundle(
        run_id=RUN_ID,
        trace_id=trace_id,
        data_classification=DataClassification.INTERNAL,
        source_availability=source_availability or _source_availability(),
        runtime=RcaRuntimeEvidence(
            evidence_ref="EV-RUNTIME-001",
            status=RcaRuntimeStatus.SUCCESS,
            created_at=NOW,
            updated_at=NOW,
            tool_call_count=1,
        ),
        llm_models=(
            RcaLlmEvidence(
                evidence_ref="EV-LLM-001",
                provider="ollama",
                model_name="qwen3.5:9b",
                status=RcaOperationStatus.OK,
                duration_ms=25,
            ),
        ),
        measurements=(
            RcaMeasurement(
                evidence_ref="EV-MEASUREMENT-001",
                name=RcaMeasurementName.INPUT_TOKENS,
                value=11,
                unit=RcaMeasurementUnit.COUNT,
                provenance=RcaMeasurementProvenance.OBSERVED,
                scope=RcaMeasurementScope.RUN,
            ),
        ),
        approval=RcaApprovalEvidence(
            evidence_ref="EV-APPROVAL-001", state=RcaApprovalState.NONE
        ),
    )


def _source_availability(
    *,
    runtime: RcaEvidenceSourceStatus = RcaEvidenceSourceStatus.AVAILABLE,
    tempo: RcaEvidenceSourceStatus = RcaEvidenceSourceStatus.AVAILABLE,
    loki: RcaEvidenceSourceStatus = RcaEvidenceSourceStatus.AVAILABLE,
    prometheus: RcaEvidenceSourceStatus = RcaEvidenceSourceStatus.AVAILABLE,
    langfuse: RcaEvidenceSourceStatus = RcaEvidenceSourceStatus.AVAILABLE,
) -> tuple[RcaSourceAvailability, ...]:
    return tuple(
        RcaSourceAvailability(
            evidence_ref=f"EV-SOURCE-{index:03}", source=source, status=status
        )
        for index, (source, status) in enumerate(
            (
                (RcaEvidenceSource.RUNTIME, runtime),
                (RcaEvidenceSource.TEMPO, tempo),
                (RcaEvidenceSource.LOKI, loki),
                (RcaEvidenceSource.PROMETHEUS, prometheus),
                (RcaEvidenceSource.LANGFUSE, langfuse),
            ),
            start=1,
        )
    )


def _finding(
    *,
    kind: RcaFindingKind | str = RcaFindingKind.DERIVED,
    evidence_refs: tuple[str, ...] = ("EV-RUNTIME-001",),
) -> RcaFinding:
    return RcaFinding(
        finding_id="F-LIFECYCLE-001",
        kind=kind,
        category=RcaFindingCategory.RUN_LIFECYCLE,
        severity=RcaSeverity.INFO,
        affected_component=RcaComponent.AGENT_RUNTIME,
        statement="The runtime record completed successfully.",
        confidence=RcaConfidence.HIGH,
        evidence_refs=evidence_refs,
    )


def _report(
    bundle: RcaEvidenceBundle,
    status: RcaAnalysisStatus,
    *,
    findings: tuple[RcaFinding, ...] = (),
) -> RcaAnalysisReport:
    available = tuple(
        item.source
        for item in bundle.source_availability
        if item.status is RcaEvidenceSourceStatus.AVAILABLE
    )
    incomplete = tuple(
        item.source
        for item in bundle.source_availability
        if item.status
        not in {
            RcaEvidenceSourceStatus.AVAILABLE,
            RcaEvidenceSourceStatus.NOT_APPLICABLE,
        }
    )
    not_applicable = tuple(
        item.source
        for item in bundle.source_availability
        if item.status is RcaEvidenceSourceStatus.NOT_APPLICABLE
    )
    return RcaAnalysisReport(
        run_id=bundle.run_id,
        trace_id=bundle.trace_id,
        analysis_status=status,
        evidence=bundle,
        deterministic_findings=findings,
        overall_limitations=(RcaLimitationCode.NO_PERFORMANCE_BASELINE,),
        completeness=RcaCompleteness(
            available_sources=available,
            incomplete_sources=incomplete,
            not_applicable_sources=not_applicable,
        ),
    )
