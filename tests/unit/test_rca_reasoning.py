import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import sleep
from uuid import UUID

import pytest

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMClient,
    LLMRequest,
    LLMResponse,
)
from industrial_ai_agent.agent.model_egress import EgressCheckedLLMClient, ExecutionZone
from industrial_ai_agent.agent.model_routing import (
    CostClass,
    DeterministicModelRouter,
    LLMCapability,
    ModelProfileMetadata,
    QualityClass,
)
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
from industrial_ai_agent.application.rca_reasoning import (
    LlmRcaReasoner,
    RcaFocus,
    RcaReasoningStatus,
    project_safe_rca_reasoning,
)
from industrial_ai_agent.domain.security import DataClassification

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
NOW = datetime(2026, 9, 6, tzinfo=UTC)


def test_reasoning_uses_authorized_report_and_preserves_hypothesis_kind() -> None:
    client = _RecordingClient(_valid_output())
    reasoner = _reasoner(client)

    result = reasoner.reason(_report(), focus=RcaFocus.OVERVIEW)

    assert result.status is RcaReasoningStatus.AVAILABLE
    assert result.confirmed_cause_present is False
    assert result.hypotheses[0].kind == "hypothesis"
    assert result.hypotheses[0].evidence_refs == ("EV-RUNTIME-001",)
    assert result.assessment.value == "completed_without_confirmed_cause"
    assert "no_confirmed_run_cause" in result.limitations
    assert len(client.calls) == 1
    request = client.calls[0][1]
    assert request.reasoning_effort.value == "none"
    assert request.response_format is not None
    assert request.response_format.type == "json_schema"
    assert request.response_format.json_schema.name == "rca_reasoning"
    assert request.response_format.json_schema.strict is True
    assert (
        request.response_format.json_schema.schema_definition["additionalProperties"]
        is False
    )
    assert (
        "limitations"
        not in request.response_format.json_schema.schema_definition["properties"]
    )
    assert request.response_format.json_schema.schema_definition["$defs"][
        "RcaReasoningAssessment"
    ]["enum"] == [
        "completed_without_confirmed_cause",
        "evidence_limited",
    ]
    system_instruction = request.messages[0].content.casefold()
    assert "root cause" not in system_instruction
    assert "confirmed cause" not in system_instruction


def test_unknown_classification_prevents_llm_invocation() -> None:
    client = _RecordingClient(_valid_output())

    result = _reasoner(client).reason(
        _report(classification=None), focus=RcaFocus.OVERVIEW
    )

    assert result.status is RcaReasoningStatus.NOT_ALLOWED
    assert client.calls == []


def test_no_eligible_egress_profile_is_not_allowed_without_provider_call() -> None:
    client = _RecordingClient(_valid_output())
    public_only = _profile("public", ExecutionZone.PUBLIC_CLOUD)
    reasoner = LlmRcaReasoner(
        router=DeterministicModelRouter(),
        profiles=(public_only,),
        client_factory=lambda classification, focus: client,
    )

    result = reasoner.reason(_report(), focus=RcaFocus.OVERVIEW)

    assert result.status is RcaReasoningStatus.NOT_ALLOWED
    assert client.calls == []


def test_final_egress_check_still_blocks_provider_after_routing() -> None:
    delegate = _RecordingClient(_valid_output())
    checked = EgressCheckedLLMClient(
        delegate,
        _FixedZoneResolver(ExecutionZone.PUBLIC_CLOUD),
        DataClassification.INTERNAL,
    )
    reasoner = LlmRcaReasoner(
        router=DeterministicModelRouter(),
        profiles=(_profile("local", ExecutionZone.LOCAL),),
        client_factory=lambda classification, focus: checked,
    )

    result = reasoner.reason(_report(), focus=RcaFocus.OVERVIEW)

    assert result.status is RcaReasoningStatus.NOT_ALLOWED
    assert delegate.calls == []


def test_safe_projection_excludes_internal_evidence_and_identifiers() -> None:
    report = _report()
    projection = project_safe_rca_reasoning(report, focus=RcaFocus.PERFORMANCE)
    rendered = json.dumps(projection.model_dump(mode="json"))

    assert projection.effective_data_classification is DataClassification.INTERNAL
    assert projection.measurements[0].provenance is RcaMeasurementProvenance.CONFIGURED
    for forbidden in ("trace_id", str(RUN_ID), "trace_spans", "raw_logs", "prompts"):
        assert forbidden not in rendered


def test_provider_output_with_unknown_fields_is_malformed() -> None:
    client = _RecordingClient(json.dumps({**_valid_output(), "unexpected": "channel"}))

    result = _reasoner(client).reason(_report(), focus=RcaFocus.OVERVIEW)

    assert result.status is RcaReasoningStatus.MALFORMED


def test_invalid_hypothesis_evidence_reference_is_malformed() -> None:
    output = _valid_output()
    output["hypotheses"][0]["evidence_refs"] = ["EV-SOURCE-001"]

    result = _reasoner(_RecordingClient(json.dumps(output))).reason(
        _report(), focus=RcaFocus.OVERVIEW
    )

    assert result.status is RcaReasoningStatus.MALFORMED


def test_root_cause_claim_and_success_to_failure_promotion_are_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    root_cause_output = _valid_output()
    root_cause_output["summary"] = "The root cause was the model."
    failed_output = _valid_output()
    failed_output["assessment"] = "failed_without_confirmed_cause"

    root_cause_result = _reasoner(
        _RecordingClient(json.dumps(root_cause_output))
    ).reason(_report(), focus=RcaFocus.OVERVIEW)
    failed_result = _reasoner(_RecordingClient(json.dumps(failed_output))).reason(
        _report(), focus=RcaFocus.OVERVIEW
    )

    assert root_cause_result.status is RcaReasoningStatus.MALFORMED
    assert failed_result.status is RcaReasoningStatus.MALFORMED
    assert "causal_claim" in caplog.text
    assert root_cause_output["summary"] not in caplog.text


def test_provider_failure_and_timeout_are_isolated() -> None:
    provider_failure = _reasoner(_FailingClient(RuntimeError("offline"))).reason(
        _report(), focus=RcaFocus.OVERVIEW
    )
    timeout = _reasoner(_FailingClient(TimeoutError("timed out"))).reason(
        _report(), focus=RcaFocus.OVERVIEW
    )

    assert provider_failure.status is RcaReasoningStatus.UNAVAILABLE
    assert timeout.status is RcaReasoningStatus.UNAVAILABLE


def test_blocking_provider_times_out_without_failing_reasoning_caller() -> None:
    result = LlmRcaReasoner(
        router=DeterministicModelRouter(),
        profiles=(_profile("local", ExecutionZone.LOCAL),),
        client_factory=lambda classification, focus: _BlockingClient(),
        timeout_seconds=0.01,
    ).reason(_report(), focus=RcaFocus.OVERVIEW)

    assert result.status is RcaReasoningStatus.UNAVAILABLE


def test_configured_cost_and_deterministic_limitations_remain_explicit() -> None:
    result = _reasoner(_RecordingClient(_valid_output())).reason(
        _report(), focus=RcaFocus.PERFORMANCE
    )

    assert RcaLimitationCode.BACKEND_UNAVAILABLE in result.limitations
    projection = project_safe_rca_reasoning(_report(), focus=RcaFocus.PERFORMANCE)
    cost = projection.measurements[0]
    assert cost.name is RcaMeasurementName.API_COST_USD
    assert cost.provenance is RcaMeasurementProvenance.CONFIGURED
    assert cost.scope is RcaMeasurementScope.MODEL_CONFIGURATION


def _reasoner(client: LLMClient) -> LlmRcaReasoner:
    return LlmRcaReasoner(
        router=DeterministicModelRouter(),
        profiles=(_profile("local", ExecutionZone.LOCAL),),
        client_factory=lambda classification, focus: client,
    )


def _profile(name: str, zone: ExecutionZone) -> ModelProfileMetadata:
    from industrial_ai_agent.agent.llm import ModelProfile

    return ModelProfileMetadata(
        profile=ModelProfile(name),
        capabilities=frozenset({LLMCapability.TEXT}),
        quality_class=QualityClass.STANDARD,
        cost_class=CostClass.LOW,
        execution_zone=zone,
    )


def _valid_output() -> str | dict[str, object]:
    return {
        "summary": "The run completed and measured LLM timing was the largest contribution.",
        "assessment": "completed_without_confirmed_cause",
        "hypotheses": [
            {
                "kind": "hypothesis",
                "statement": "A targeted timing check may clarify the observed contribution.",
                "confidence": "low",
                "evidence_refs": ["EV-RUNTIME-001"],
            }
        ],
        "recommended_next_checks": [
            "Inspect bounded timing evidence if more detail is needed."
        ],
    }


def _report(
    *, classification: DataClassification | None = DataClassification.INTERNAL
) -> RcaAnalysisReport:
    source_statuses = tuple(
        RcaSourceAvailability(
            evidence_ref=f"EV-SOURCE-{index:03}",
            source=source,
            status=(
                RcaEvidenceSourceStatus.UNAVAILABLE
                if source is RcaEvidenceSource.LOKI
                else RcaEvidenceSourceStatus.AVAILABLE
            ),
            limitations=(
                (RcaLimitationCode.BACKEND_UNAVAILABLE,)
                if source is RcaEvidenceSource.LOKI
                else ()
            ),
        )
        for index, source in enumerate(RcaEvidenceSource, start=1)
    )
    evidence = RcaEvidenceBundle(
        run_id=RUN_ID,
        data_classification=classification,
        source_availability=source_statuses,
        runtime=RcaRuntimeEvidence(
            evidence_ref="EV-RUNTIME-001",
            status=RcaRuntimeStatus.SUCCESS,
            run_profile="INTERNAL_DIAGNOSTIC",
            model_profile="local_quality",
            created_at=NOW,
            updated_at=NOW,
            tool_call_count=0,
        ),
        measurements=(
            RcaMeasurement(
                evidence_ref="EV-MEASUREMENT-001",
                name=RcaMeasurementName.API_COST_USD,
                value=0,
                unit=RcaMeasurementUnit.USD,
                provenance=RcaMeasurementProvenance.CONFIGURED,
                scope=RcaMeasurementScope.MODEL_CONFIGURATION,
            ),
        ),
    )
    return RcaAnalysisReport(
        run_id=RUN_ID,
        analysis_status=RcaAnalysisStatus.PARTIAL,
        evidence=evidence,
        deterministic_findings=(
            RcaFinding(
                finding_id="F-OBSERVED-001",
                kind=RcaFindingKind.OBSERVED,
                category=RcaFindingCategory.RUN_LIFECYCLE,
                severity=RcaSeverity.INFO,
                affected_component=RcaComponent.AGENT_RUNTIME,
                statement="Run completed successfully.",
                confidence=RcaConfidence.HIGH,
                evidence_refs=("EV-RUNTIME-001",),
            ),
        ),
        overall_limitations=(RcaLimitationCode.BACKEND_UNAVAILABLE,),
        completeness=RcaCompleteness(
            available_sources=tuple(
                source
                for source in RcaEvidenceSource
                if source is not RcaEvidenceSource.LOKI
            ),
            incomplete_sources=(RcaEvidenceSource.LOKI,),
            not_applicable_sources=(),
        ),
    )


@dataclass
class _RecordingClient(LLMClient):
    output: str | dict[str, object]
    calls: list[tuple[object, LLMRequest]] = field(default_factory=list)

    def chat(self, profile: object, request: LLMRequest) -> LLMResponse:
        self.calls.append((profile, request))
        return LLMResponse(
            text=self.output
            if isinstance(self.output, str)
            else json.dumps(self.output),
            finish_reason=FinishReason.STOP,
        )


@dataclass
class _FailingClient(LLMClient):
    error: Exception

    def chat(self, profile: object, request: LLMRequest) -> LLMResponse:
        del profile, request
        raise self.error


class _BlockingClient(LLMClient):
    def chat(self, profile: object, request: LLMRequest) -> LLMResponse:
        del profile, request
        sleep(0.05)
        return LLMResponse(
            text=json.dumps(_valid_output()), finish_reason=FinishReason.STOP
        )


@dataclass(frozen=True)
class _FixedZoneResolver:
    zone: ExecutionZone

    def get_execution_zone(self, profile_name: str) -> ExecutionZone:
        del profile_name
        return self.zone
