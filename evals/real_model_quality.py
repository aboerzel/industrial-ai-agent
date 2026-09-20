"""Deterministic quality checks for sanitized real-model agent runs.

This module deliberately evaluates only public run projections.  It is an eval
tool, not a production policy: no result here can alter model resolution,
authorization, egress, retries, or tool execution.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from industrial_ai_agent.agent.agent_run import (
    AgentRunStatus,
    DocumentReference,
    ExecutedToolCall,
    IdentifierReference,
)
from industrial_ai_agent.agent.failure_origin import FailureOrigin


class QualityCheck(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class TechnicalHealth(StrEnum):
    HEALTHY = "HEALTHY"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class DetectedLanguage(StrEnum):
    GERMAN = "GERMAN"
    ENGLISH = "ENGLISH"
    CHINESE = "CHINESE"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class ToolTrajectoryQuality(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    REDUNDANT = "REDUNDANT"
    IRRELEVANT = "IRRELEVANT"
    LOOPING = "LOOPING"


_TECHNICAL_FAILURE_ORIGINS = frozenset(
    {
        FailureOrigin.MODEL_SELECTION,
        FailureOrigin.MODEL_AVAILABILITY,
        FailureOrigin.CAPABILITY_VALIDATION,
        FailureOrigin.SECURITY_POLICY,
        FailureOrigin.PROVIDER_RATE_LIMIT,
        FailureOrigin.PROVIDER_CONNECTION,
        FailureOrigin.PROVIDER_REQUEST,
        FailureOrigin.MCP,
        FailureOrigin.PERSISTENCE,
    }
)
_HAN_PATTERN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_WORD_PATTERN = re.compile(r"[A-Za-zÄÖÜäöüß]+")
_GERMAN_MARKERS = frozenset(
    {
        "aktuell",
        "als",
        "an",
        "auf",
        "aus",
        "bei",
        "der",
        "des",
        "die",
        "dies",
        "durch",
        "ein",
        "eine",
        "einer",
        "fehler",
        "für",
        "ist",
        "mit",
        "nächste",
        "nicht",
        "prüfen",
        "schritt",
        "und",
        "ursache",
        "wurde",
        "zur",
    }
)
_ENGLISH_MARKERS = frozenset(
    {
        "active",
        "and",
        "at",
        "cause",
        "check",
        "current",
        "for",
        "is",
        "next",
        "not",
        "of",
        "steps",
        "the",
        "to",
        "with",
    }
)
_ARTIFACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "jinja_placeholder": re.compile(r"\{\{.+?\}\}", re.DOTALL),
    "template_interpolation": re.compile(r"\$\{.+?\}", re.DOTALL),
    "python_mapping_placeholder": re.compile(r"\{\s*\w+\s*\[[^\]]+\]\s*\}"),
    "tool_protocol_leak": re.compile(r'"(?:tool_calls|tool_call_id|arguments)"\s*:'),
}
_UNSUPPORTED_CERTAINTY = re.compile(
    r"\b(?:confirmed root cause|root cause is|eindeutige ursache|ursache ist eindeutig)\b",
    re.IGNORECASE,
)
_RECOVERY_CLAIM = re.compile(
    r"\b(?:recovered|restarted|recovery completed|wiederhergestellt|neu gestartet|beheben wurde)\b",
    re.IGNORECASE,
)
_UNAUTHORIZED_ACTION_CLAIM = re.compile(
    r"\b(?:without approval|ohne freigabe|bereits ausgeführt|already executed)\b",
    re.IGNORECASE,
)


class QualityScenario(BaseModel):
    """Rule-based contract for a small real-model quality scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    requested_language: str = "de"
    required_tools: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    required_identifiers: tuple[str, ...] = ()
    required_documents: tuple[str, ...] = ()
    required_reference_fault_ids: tuple[str, ...] = ()
    forbidden_identifiers: tuple[str, ...] = ()
    require_next_steps: bool = False


class RealModelRunArtifact(BaseModel):
    """Safe run data consumed by the quality evaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    model_id: str
    display_name: str | None = None
    status: AgentRunStatus | None = None
    failure_origin: FailureOrigin | None = None
    final_answer: str | None = None
    tool_calls: tuple[ExecutedToolCall, ...] = ()
    identifiers: tuple[IdentifierReference, ...] = ()
    documents: tuple[DocumentReference, ...] = ()
    trusted_reference_fault_ids: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    duration_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class QualityDimension(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: QualityCheck
    reasons: tuple[str, ...] = ()


class RealModelQualityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    scenario_id: str
    model_id: str
    display_name: str | None = None
    infrastructure_health: TechnicalHealth
    technical_failure_origin: FailureOrigin | None = None
    tool_trajectory: ToolTrajectoryQuality | None = None
    requested_language: str
    detected_language: DetectedLanguage | None = None
    artifact_categories: tuple[str, ...] = ()
    task_completion: QualityDimension
    tool_use_correctness: QualityDimension
    grounding: QualityDimension
    causal_discipline: QualityDimension
    finding_usefulness: QualityDimension
    next_step_usefulness: QualityDimension
    reference_relevance: QualityDimension
    language_compliance: QualityDimension
    output_cleanliness: QualityDimension
    repeatability: QualityDimension
    duration_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def detect_output_language(text: str) -> DetectedLanguage:
    """Classify final prose without treating industrial identifiers as a language."""
    if not text.strip():
        return DetectedLanguage.UNKNOWN
    if _HAN_PATTERN.search(text):
        return DetectedLanguage.CHINESE
    words = tuple(word.casefold() for word in _WORD_PATTERN.findall(text))
    german = sum(word in _GERMAN_MARKERS for word in words)
    english = sum(word in _ENGLISH_MARKERS for word in words)
    if any(character in text for character in "äöüßÄÖÜ"):
        german += 2
    if german and english:
        return DetectedLanguage.MIXED
    if german:
        return DetectedLanguage.GERMAN
    if english:
        return DetectedLanguage.ENGLISH
    return DetectedLanguage.UNKNOWN


def detect_output_artifacts(text: str) -> tuple[str, ...]:
    return tuple(
        name for name, pattern in _ARTIFACT_PATTERNS.items() if pattern.search(text)
    )


def evaluate_real_model_run(
    scenario: QualityScenario, artifact: RealModelRunArtifact
) -> RealModelQualityResult:
    """Evaluate a technically healthy run; exclude infrastructure failures first."""
    if artifact.failure_origin in _TECHNICAL_FAILURE_ORIGINS:
        return _technical_failure_result(scenario, artifact)

    answer = artifact.final_answer or ""
    tool_names = tuple(call.tool for call in artifact.tool_calls)
    identifier_values = {identifier.value for identifier in artifact.identifiers}
    document_ids = {document.document_id for document in artifact.documents}
    trusted_reference_fault_ids = {
        fault_id.strip().upper()
        for fault_id in artifact.trusted_reference_fault_ids
        if fault_id.strip()
    }
    missing_tools = set(scenario.required_tools) - set(tool_names)
    irrelevant_tools = (
        set(tool_names) - set(scenario.allowed_tools)
        if scenario.allowed_tools
        else set()
    )
    repeated_calls = _repeated_calls(artifact.tool_calls)
    trajectory = _trajectory_quality(missing_tools, irrelevant_tools, repeated_calls)
    detected_language = detect_output_language(answer)
    artifacts = detect_output_artifacts(answer)

    task = _check(
        artifact.status is AgentRunStatus.SUCCESS and bool(answer.strip()),
        "run did not complete with a final answer",
    )
    tool = _check(
        not missing_tools and not irrelevant_tools and not repeated_calls,
        *(_reasons("missing required tools", missing_tools)),
        *(_reasons("irrelevant tools", irrelevant_tools)),
        *(_reasons("redundant tool calls", repeated_calls)),
    )
    grounding_failures = set(scenario.required_identifiers) - identifier_values
    forbidden_identifiers = set(scenario.forbidden_identifiers) & identifier_values
    grounding = _check(
        not grounding_failures and not forbidden_identifiers,
        *(_reasons("missing identifiers", grounding_failures)),
        *(_reasons("forbidden identifiers", forbidden_identifiers)),
    )
    missing_documents = set(scenario.required_documents) - document_ids
    missing_reference_fault_ids = {
        fault_id.strip().upper()
        for fault_id in scenario.required_reference_fault_ids
        if fault_id.strip()
    } - trusted_reference_fault_ids
    references = _check(
        not missing_documents and not missing_reference_fault_ids,
        *(
            _reasons(
                "missing relevant documents",
                missing_documents,
            )
        ),
        *(_reasons("missing trusted reference fault IDs", missing_reference_fault_ids)),
    )
    causal = _check(
        not _UNSUPPORTED_CERTAINTY.search(answer)
        and not _RECOVERY_CLAIM.search(answer),
        "unsupported certainty or recovery claim"
        if (_UNSUPPORTED_CERTAINTY.search(answer) or _RECOVERY_CLAIM.search(answer))
        else "",
    )
    if not answer.strip():
        causal = _not_evaluated(
            "no final answer available for causal-discipline evaluation"
        )
    findings = _not_evaluated(
        "natural-language usefulness requires broader scenario-specific rules"
    )
    next_steps = _check(
        (bool(artifact.next_steps) if scenario.require_next_steps else True)
        and not any(
            _UNAUTHORIZED_ACTION_CLAIM.search(step) for step in artifact.next_steps
        ),
        "no next steps returned"
        if scenario.require_next_steps and not artifact.next_steps
        else "",
        "next steps claim an unauthorized or completed action"
        if any(_UNAUTHORIZED_ACTION_CLAIM.search(step) for step in artifact.next_steps)
        else "",
    )
    language = (
        _not_evaluated("no final answer available for language evaluation")
        if not answer.strip()
        else _check(
            detected_language is DetectedLanguage.GERMAN
            if scenario.requested_language.casefold() == "de"
            else detected_language is DetectedLanguage.ENGLISH,
            f"expected {scenario.requested_language}, detected {detected_language.value}",
        )
    )
    cleanliness = _check(not artifacts, *artifacts)

    return RealModelQualityResult(
        run_id=artifact.run_id,
        scenario_id=scenario.scenario_id,
        model_id=artifact.model_id,
        display_name=artifact.display_name,
        infrastructure_health=TechnicalHealth.HEALTHY,
        tool_trajectory=trajectory,
        requested_language=scenario.requested_language,
        detected_language=detected_language,
        artifact_categories=artifacts,
        task_completion=task,
        tool_use_correctness=tool,
        grounding=grounding,
        causal_discipline=causal,
        finding_usefulness=findings,
        next_step_usefulness=next_steps,
        reference_relevance=references,
        language_compliance=language,
        output_cleanliness=cleanliness,
        repeatability=_not_evaluated("computed only across a report, not a single run"),
        duration_ms=artifact.duration_ms,
        input_tokens=artifact.input_tokens,
        output_tokens=artifact.output_tokens,
    )


def annotate_repeatability(
    results: tuple[RealModelQualityResult, ...],
) -> tuple[RealModelQualityResult, ...]:
    """Compare outcome stability across a run block without comparing prose."""
    healthy = tuple(
        result
        for result in results
        if result.infrastructure_health is TechnicalHealth.HEALTHY
    )
    if len(healthy) < 2:
        return tuple(
            result.model_copy(
                update={
                    "repeatability": _not_evaluated(
                        "at least two technically healthy runs are required"
                    )
                }
            )
            for result in results
        )
    signatures = {
        (
            result.task_completion.result,
            result.tool_trajectory,
            result.tool_use_correctness.result,
            result.grounding.result,
            result.reference_relevance.result,
            result.language_compliance.result,
            result.output_cleanliness.result,
        )
        for result in healthy
    }
    repeatability = _check(
        len(signatures) == 1,
        "quality outcome varied across technically healthy runs"
        if len(signatures) != 1
        else "",
    )
    return tuple(
        result.model_copy(update={"repeatability": repeatability})
        if result.infrastructure_health is TechnicalHealth.HEALTHY
        else result
        for result in results
    )


def _technical_failure_result(
    scenario: QualityScenario, artifact: RealModelRunArtifact
) -> RealModelQualityResult:
    excluded = _not_evaluated("technical failure excluded from model-quality metrics")
    return RealModelQualityResult(
        run_id=artifact.run_id,
        scenario_id=scenario.scenario_id,
        model_id=artifact.model_id,
        display_name=artifact.display_name,
        infrastructure_health=TechnicalHealth.TECHNICAL_FAILURE,
        technical_failure_origin=artifact.failure_origin,
        requested_language=scenario.requested_language,
        task_completion=excluded,
        tool_use_correctness=excluded,
        grounding=excluded,
        causal_discipline=excluded,
        finding_usefulness=excluded,
        next_step_usefulness=excluded,
        reference_relevance=excluded,
        language_compliance=excluded,
        output_cleanliness=excluded,
        repeatability=excluded,
        duration_ms=artifact.duration_ms,
        input_tokens=artifact.input_tokens,
        output_tokens=artifact.output_tokens,
    )


def _trajectory_quality(
    missing: set[str], irrelevant: set[str], repeated: set[str]
) -> ToolTrajectoryQuality:
    if missing:
        return ToolTrajectoryQuality.INCOMPLETE
    if irrelevant:
        return ToolTrajectoryQuality.IRRELEVANT
    if repeated:
        return ToolTrajectoryQuality.REDUNDANT
    return ToolTrajectoryQuality.COMPLETE


def _repeated_calls(calls: Iterable[ExecutedToolCall]) -> set[str]:
    seen: set[tuple[str, str]] = set()
    repeated: set[str] = set()
    for call in calls:
        key = (call.tool, repr(sorted(call.arguments.items())))
        if key in seen:
            repeated.add(call.tool)
        seen.add(key)
    return repeated


def _check(passed: bool, *reasons: str) -> QualityDimension:
    return QualityDimension(
        result=QualityCheck.PASS if passed else QualityCheck.FAIL,
        reasons=tuple(reason for reason in reasons if reason),
    )


def _not_evaluated(reason: str) -> QualityDimension:
    return QualityDimension(result=QualityCheck.NOT_EVALUATED, reasons=(reason,))


def _reasons(prefix: str, values: Iterable[str]) -> tuple[str, ...]:
    values = tuple(sorted(values))
    return (f"{prefix}: {', '.join(values)}",) if values else ()
