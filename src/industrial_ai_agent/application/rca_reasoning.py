"""Optional, provider-independent explanation over an immutable RCA report."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMJsonSchema,
    LLMMessage,
    LLMReasoningEffort,
    LLMRequest,
    LLMResponseFormat,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.agent.model_egress import ModelEgressDeniedError
from industrial_ai_agent.agent.model_routing import (
    CostPreference,
    DeterministicModelRouter,
    LLMCapability,
    ModelProfileMetadata,
    NoEligibleModelError,
    QualityClass,
    TaskRequirements,
    TaskRole,
)
from industrial_ai_agent.application.rca import (
    BoundedText,
    EvidenceReference,
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
from industrial_ai_agent.domain.security import DataClassification

_LOGGER = logging.getLogger(__name__)


class RcaFocus(StrEnum):
    OVERVIEW = "overview"
    FAILURE = "failure"
    PERFORMANCE = "performance"


class RcaReasoningStatus(StrEnum):
    AVAILABLE = "available"
    NOT_REQUESTED = "not_requested"
    NOT_ALLOWED = "not_allowed"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"


class RcaReasoningAssessment(StrEnum):
    COMPLETED_WITHOUT_CONFIRMED_CAUSE = "completed_without_confirmed_cause"
    FAILED_WITHOUT_CONFIRMED_CAUSE = "failed_without_confirmed_cause"
    EVIDENCE_LIMITED = "evidence_limited"
    CONFIRMED_CAUSE_PRESENT = "confirmed_cause_present"


class RcaReasoningLimitation(StrEnum):
    NO_CONFIRMED_RUN_CAUSE = "no_confirmed_run_cause"


class _RcaReasoningModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RcaReasoningHypothesis(_RcaReasoningModel):
    """An LLM hypothesis, deliberately separate from deterministic findings."""

    kind: Literal["hypothesis"] = "hypothesis"
    statement: BoundedText
    confidence: RcaConfidence
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_unique_evidence_references(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("reasoning hypothesis evidence references must be unique")
        return self


class RcaReasoningResult(_RcaReasoningModel):
    """Bounded output exposed after optional LLM explanation."""

    status: RcaReasoningStatus
    confirmed_cause_present: bool
    summary: BoundedText | None = None
    assessment: RcaReasoningAssessment | None = None
    hypotheses: tuple[RcaReasoningHypothesis, ...] = Field(default=(), max_length=5)
    recommended_next_checks: tuple[BoundedText, ...] = Field(default=(), max_length=5)
    limitations: tuple[RcaLimitationCode | RcaReasoningLimitation, ...] = Field(
        default=(), max_length=21
    )

    @model_validator(mode="after")
    def validate_status_shape(self) -> Self:
        if self.status is RcaReasoningStatus.AVAILABLE:
            if self.summary is None or self.assessment is None:
                raise ValueError("available reasoning requires summary and assessment")
            return self
        if any(
            (
                self.summary is not None,
                self.assessment is not None,
                self.hypotheses,
                self.recommended_next_checks,
            )
        ):
            raise ValueError("unavailable reasoning must not include model content")
        return self

    @classmethod
    def unavailable(
        cls,
        status: RcaReasoningStatus,
        report: RcaAnalysisReport,
    ) -> RcaReasoningResult:
        return cls(
            status=status,
            confirmed_cause_present=_has_confirmed_cause(report),
            limitations=_deterministic_reasoning_limitations(report),
        )


class _SafeSourceStatus(_RcaReasoningModel):
    source: RcaEvidenceSource
    status: RcaEvidenceSourceStatus
    limitations: tuple[RcaLimitationCode, ...]


class _SafeFinding(_RcaReasoningModel):
    finding_id: str
    kind: RcaFindingKind
    category: RcaFindingCategory
    severity: RcaSeverity
    affected_component: RcaComponent
    statement: BoundedText
    confidence: RcaConfidence
    evidence_refs: tuple[EvidenceReference, ...]


class _SafeMeasurement(_RcaReasoningModel):
    name: RcaMeasurementName
    value: float = Field(ge=0)
    unit: RcaMeasurementUnit
    provenance: RcaMeasurementProvenance
    scope: RcaMeasurementScope


class SafeRcaReasoningProjection(_RcaReasoningModel):
    """The sole model input; it intentionally omits raw evidence and identifiers."""

    focus: RcaFocus
    run_profile: str | None
    effective_data_classification: DataClassification
    analysis_status: RcaAnalysisStatus
    runtime_status: RcaRuntimeStatus | None
    available_sources: tuple[RcaEvidenceSource, ...]
    incomplete_sources: tuple[RcaEvidenceSource, ...]
    source_statuses: tuple[_SafeSourceStatus, ...]
    findings: tuple[_SafeFinding, ...]
    measurements: tuple[_SafeMeasurement, ...]
    limitations: tuple[RcaLimitationCode, ...]
    confirmed_cause_present: bool
    allowed_evidence_refs: tuple[EvidenceReference, ...]


class RcaReasoner(Protocol):
    """Application boundary for optional explanation of an authorized report."""

    def reason(
        self,
        report: RcaAnalysisReport,
        *,
        focus: RcaFocus,
    ) -> RcaReasoningResult: ...


class LlmRcaReasoner:
    """Use the existing routed, egress-checked LLM client with strict output parsing."""

    def __init__(
        self,
        *,
        router: DeterministicModelRouter,
        profiles: tuple[ModelProfileMetadata, ...],
        client_factory: Callable[[DataClassification, RcaFocus], LLMClient],
        timeout_seconds: float = 30,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("RCA reasoning timeout must be positive")
        self._router = router
        self._profiles = profiles
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    def reason(
        self,
        report: RcaAnalysisReport,
        *,
        focus: RcaFocus,
    ) -> RcaReasoningResult:
        classification = report.evidence.data_classification
        if not isinstance(classification, DataClassification):
            return RcaReasoningResult.unavailable(
                RcaReasoningStatus.NOT_ALLOWED, report
            )

        projection = project_safe_rca_reasoning(report, focus=focus)
        requirements = reasoning_task_requirements(classification)
        try:
            profile = self._router.route(requirements, self._profiles)
            response = _chat_with_timeout(
                self._client_factory(classification, focus),
                profile,
                _reasoning_request(projection, report),
                timeout_seconds=self._timeout_seconds,
            )
        except (NoEligibleModelError, ModelEgressDeniedError):
            return RcaReasoningResult.unavailable(
                RcaReasoningStatus.NOT_ALLOWED, report
            )
        except Exception:  # noqa: BLE001 - optional reasoning must not affect RCA.
            return RcaReasoningResult.unavailable(
                RcaReasoningStatus.UNAVAILABLE, report
            )

        try:
            output = _RcaReasoningProviderOutput.model_validate_json(response.text)
        except (TypeError, ValueError, ValidationError) as error:
            _log_malformed_reasoning_output(error)
            return RcaReasoningResult.unavailable(RcaReasoningStatus.MALFORMED, report)
        try:
            return _validated_result(output, report, projection)
        except ValueError as error:
            _log_malformed_reasoning_output(error)
            return RcaReasoningResult.unavailable(RcaReasoningStatus.MALFORMED, report)


def _chat_with_timeout(
    client: LLMClient,
    profile: ModelProfile,
    request: LLMRequest,
    *,
    timeout_seconds: float,
):
    """Bound optional provider waiting without delaying deterministic RCA output."""
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rca-reasoning")
    future = executor.submit(client.chat, profile, request)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as error:
        future.cancel()
        raise TimeoutError("RCA reasoning timed out") from error
    finally:
        # An in-flight provider call cannot be force-cancelled safely. Detach it because
        # reasoning is optional and the deterministic response must remain available.
        executor.shutdown(wait=False, cancel_futures=True)


class _RcaReasoningProviderOutput(_RcaReasoningModel):
    summary: BoundedText
    assessment: RcaReasoningAssessment
    hypotheses: tuple[RcaReasoningHypothesis, ...] = Field(default=(), max_length=5)
    recommended_next_checks: tuple[BoundedText, ...] = Field(default=(), max_length=5)


def reasoning_task_requirements(
    classification: DataClassification,
) -> TaskRequirements:
    """Server-owned requirements for concise, text-only RCA explanation."""
    return TaskRequirements(
        task_role=TaskRole.GENERAL_REASONING,
        required_capabilities=frozenset({LLMCapability.TEXT}),
        minimum_quality=QualityClass.STANDARD,
        cost_preference=CostPreference.MINIMIZE_COST,
        data_classification=classification,
    )


def project_safe_rca_reasoning(
    report: RcaAnalysisReport,
    *,
    focus: RcaFocus,
) -> SafeRcaReasoningProjection:
    """Construct a bounded model input without serializing internal RCA evidence."""
    classification = report.evidence.data_classification
    if not isinstance(classification, DataClassification):
        raise TypeError("RCA reasoning requires a known data classification")
    allowed_evidence_refs = tuple(
        sorted(
            {
                reference
                for finding in report.deterministic_findings
                for reference in finding.evidence_refs
            }
        )
    )
    return SafeRcaReasoningProjection(
        focus=focus,
        run_profile=(
            report.evidence.runtime.run_profile if report.evidence.runtime else None
        ),
        effective_data_classification=classification,
        analysis_status=report.analysis_status,
        runtime_status=(
            report.evidence.runtime.status if report.evidence.runtime else None
        ),
        available_sources=report.completeness.available_sources,
        incomplete_sources=report.completeness.incomplete_sources,
        source_statuses=tuple(
            _SafeSourceStatus(
                source=item.source,
                status=item.status,
                limitations=item.limitations,
            )
            for item in report.evidence.source_availability
        ),
        findings=tuple(
            _SafeFinding(
                finding_id=finding.finding_id,
                kind=finding.kind,
                category=finding.category,
                severity=finding.severity,
                affected_component=finding.affected_component,
                statement=finding.statement,
                confidence=finding.confidence,
                evidence_refs=finding.evidence_refs,
            )
            for finding in report.deterministic_findings
        ),
        measurements=tuple(
            _SafeMeasurement(
                name=measurement.name,
                value=measurement.value,
                unit=measurement.unit,
                provenance=measurement.provenance,
                scope=measurement.scope,
            )
            for measurement in report.evidence.measurements
        ),
        limitations=report.overall_limitations,
        confirmed_cause_present=_has_confirmed_cause(report),
        allowed_evidence_refs=allowed_evidence_refs,
    )


def _reasoning_request(
    projection: SafeRcaReasoningProjection,
    report: RcaAnalysisReport,
) -> LLMRequest:
    return LLMRequest(
        messages=(
            LLMMessage(role=MessageRole.SYSTEM, content=_SYSTEM_INSTRUCTION),
            LLMMessage(
                role=MessageRole.USER,
                content=json.dumps(projection.model_dump(mode="json"), sort_keys=True),
            ),
        ),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="rca_reasoning",
                schema_definition=_reasoning_output_schema(report),
            )
        ),
        reasoning_effort=LLMReasoningEffort.NONE,
    )


def _reasoning_output_schema(report: RcaAnalysisReport) -> dict[str, object]:
    """Narrow the provider enum to assessments consistent with immutable runtime state."""
    schema = _RcaReasoningProviderOutput.model_json_schema()
    assessment_definition = schema["$defs"]["RcaReasoningAssessment"]
    assessment_definition["enum"] = sorted(
        assessment.value for assessment in _allowed_assessments(report)
    )
    return schema


def _validated_result(
    output: _RcaReasoningProviderOutput,
    report: RcaAnalysisReport,
    projection: SafeRcaReasoningProjection,
) -> RcaReasoningResult:
    _validate_epistemic_output(output, report, projection)
    return RcaReasoningResult(
        status=RcaReasoningStatus.AVAILABLE,
        confirmed_cause_present=projection.confirmed_cause_present,
        summary=output.summary,
        assessment=output.assessment,
        hypotheses=output.hypotheses,
        recommended_next_checks=output.recommended_next_checks,
        limitations=_deterministic_reasoning_limitations(report),
    )


def _log_malformed_reasoning_output(error: Exception) -> None:
    """Record bounded validation metadata without retaining provider output."""
    if isinstance(error, ValidationError):
        paths = tuple(
            ".".join(str(part) for part in item["loc"])
            for item in error.errors(include_url=False, include_input=False)
        )
        _LOGGER.warning("RCA reasoning schema validation failed at paths=%s", paths)
        return
    _LOGGER.warning(
        "RCA reasoning policy validation failed category=%s",
        _reasoning_validation_category(error),
    )


def _reasoning_validation_category(error: Exception) -> str:
    message = str(error)
    if "assessment conflicts" in message:
        return "assessment_conflict"
    if "referenced unavailable evidence" in message:
        return "invalid_evidence_reference"
    if "root-cause claims" in message:
        return "causal_claim"
    if "excluded payload data" in message:
        return "excluded_payload_reference"
    return "unexpected_validation_error"


def _validate_epistemic_output(
    output: _RcaReasoningProviderOutput,
    report: RcaAnalysisReport,
    projection: SafeRcaReasoningProjection,
) -> None:
    allowed_assessments = _allowed_assessments(report)
    if output.assessment not in allowed_assessments:
        raise ValueError(
            "reasoning assessment conflicts with deterministic runtime state"
        )
    allowed_references = set(projection.allowed_evidence_refs)
    if any(
        reference not in allowed_references
        for hypothesis in output.hypotheses
        for reference in hypothesis.evidence_refs
    ):
        raise ValueError("reasoning hypothesis referenced unavailable evidence")
    model_text = " ".join(
        (
            output.summary,
            *(hypothesis.statement for hypothesis in output.hypotheses),
            *output.recommended_next_checks,
        )
    ).casefold()
    if "root cause" in model_text or "confirmed cause" in model_text:
        raise ValueError("reasoning may not create or restate root-cause claims")
    if any(
        forbidden in model_text
        for forbidden in (
            "prompt",
            "model response",
            "tool argument",
            "tool result",
            "retrieved document",
            "raw log",
            "authorization header",
            "backend url",
            "sql",
        )
    ):
        raise ValueError("reasoning output attempted to infer excluded payload data")


def _allowed_assessments(
    report: RcaAnalysisReport,
) -> frozenset[RcaReasoningAssessment]:
    if _has_confirmed_cause(report):
        return frozenset({RcaReasoningAssessment.CONFIRMED_CAUSE_PRESENT})
    if (
        report.evidence.runtime
        and report.evidence.runtime.status is RcaRuntimeStatus.FAILED
    ):
        return frozenset(
            {
                RcaReasoningAssessment.FAILED_WITHOUT_CONFIRMED_CAUSE,
                RcaReasoningAssessment.EVIDENCE_LIMITED,
            }
        )
    return frozenset(
        {
            RcaReasoningAssessment.COMPLETED_WITHOUT_CONFIRMED_CAUSE,
            RcaReasoningAssessment.EVIDENCE_LIMITED,
        }
    )


def _has_confirmed_cause(report: RcaAnalysisReport) -> bool:
    return any(
        finding.kind is RcaFindingKind.CONFIRMED_RUN_CAUSE
        for finding in report.deterministic_findings
    )


def _deterministic_reasoning_limitations(
    report: RcaAnalysisReport,
) -> tuple[RcaLimitationCode | RcaReasoningLimitation, ...]:
    limitations: list[RcaLimitationCode | RcaReasoningLimitation] = list(
        report.overall_limitations
    )
    if not _has_confirmed_cause(report):
        limitations.append(RcaReasoningLimitation.NO_CONFIRMED_RUN_CAUSE)
    return tuple(limitations)


_SYSTEM_INSTRUCTION = (
    "Return only one JSON object with summary, assessment, hypotheses, and "
    "recommended_next_checks. Hypotheses contain statement, confidence, and evidence_refs; "
    "do not add fields or limitations: deterministic limitations are retained by the server. "
    "The supplied structured "
    "RCA data is the only evidence. Deterministic findings are immutable: do not change "
    "their kinds, confidence, evidence, limitations, or source status. Do not make causal "
    "assertions; the server retains causal-status limitations. Label every hypothesis as "
    "hypothesis and cite only supplied evidence references. Missing evidence remains missing. Do not describe a successful "
    "run as failed, do not call a dominant timing component a cause, and do not treat "
    "configured cost as observed cost. Do not infer prompts, responses, tool or document "
    "content, raw logs, SQL, credentials, headers, URLs, or hidden data."
)
