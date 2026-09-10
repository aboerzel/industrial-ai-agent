"""Evaluate bounded, provider-independent Golden Agent-run contracts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from evals.run_outcome import AcceptanceOutcome, classify_run_outcome
from industrial_ai_agent.agent.agent_run import (
    DocumentReference,
    ExecutedToolCall,
    IdentifierReference,
    InvestigationStep,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "evals" / "golden" / "v1" / "cases.json"


class GoldenOutcome(StrEnum):
    SUCCESS = "success"
    EXPECTED_NON_DISCLOSURE = "expected_non_disclosure"
    BLOCKED_BY_PROVIDER = "blocked_by_provider"
    FAIL = "fail"


class GoldenExpected(BaseModel):
    """Deterministic assertions over the public, authorized run projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: GoldenOutcome
    expected_error_code: str | None = None
    expected_tools: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    min_tool_calls: int = Field(default=0, ge=0)
    max_tool_calls: int = Field(default=4, ge=0, le=4)
    exact_tool_order: tuple[str, ...] = ()
    expected_identifiers: tuple[str, ...] = ()
    forbidden_identifiers: tuple[str, ...] = ()
    expected_documents: tuple[str, ...] = ()
    forbidden_documents: tuple[str, ...] = ()
    required_answer_facts: tuple[str, ...] = ()
    forbidden_answer_claims: tuple[str, ...] = ()
    require_investigation_steps: bool = False
    max_next_steps: int = Field(default=5, ge=0, le=5)
    require_next_steps: bool = False
    neutral_non_disclosure: bool = False

    @model_validator(mode="after")
    def validate_consistency(self) -> GoldenExpected:
        if self.min_tool_calls > self.max_tool_calls:
            raise ValueError("min_tool_calls must not exceed max_tool_calls")
        if (
            self.expected_tools
            and self.allowed_tools
            and not set(self.expected_tools).issubset(self.allowed_tools)
        ):
            raise ValueError("expected_tools must be allowed when allowed_tools is set")
        if set(self.expected_tools) & set(self.forbidden_tools):
            raise ValueError("expected_tools must not contain forbidden_tools")
        if self.exact_tool_order and not set(self.exact_tool_order).issubset(
            self.expected_tools
        ):
            raise ValueError("exact_tool_order must contain expected tools only")
        if self.neutral_non_disclosure:
            if self.outcome is not GoldenOutcome.EXPECTED_NON_DISCLOSURE:
                raise ValueError(
                    "neutral_non_disclosure requires expected_non_disclosure outcome"
                )
            if (
                self.expected_tools
                or self.expected_identifiers
                or self.expected_documents
            ):
                raise ValueError("non-disclosure must not expect protected artifacts")
        return self


class GoldenCase(BaseModel):
    """A versioned, reviewable scenario anchored in FACTORY-DEMO-01 fixtures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    request: str = Field(min_length=1, max_length=2_000)
    response_language: Literal["DE", "EN"]
    clearance: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    tags: tuple[str, ...] = ()
    expected: GoldenExpected
    equivalent_case_id: str | None = None

    @model_validator(mode="after")
    def normalize_and_validate_id(self) -> GoldenCase:
        if self.id != self.id.strip():
            raise ValueError("id must not have surrounding whitespace")
        if self.equivalent_case_id == self.id:
            raise ValueError("equivalent_case_id must not reference the same case")
        return self


class GoldenArtifact(BaseModel):
    """Sanitized outcome supplied by an Agent test, integration test, or live harness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["success", "failed", "denied"]
    response_language: Literal["DE", "EN"]
    final_answer: str = ""
    error_code: str | None = None
    provider_error_code: str | None = None
    tool_calls: tuple[ExecutedToolCall, ...] = ()
    investigation_steps: tuple[InvestigationStep, ...] = ()
    identifiers: tuple[IdentifierReference, ...] = ()
    documents: tuple[DocumentReference, ...] = ()
    next_steps: tuple[str, ...] = ()


class GoldenCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    expected: str
    actual: str
    severity: Literal["critical", "error"] = "error"


class GoldenCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    passed: bool
    checks: tuple[GoldenCheck, ...]


class GoldenEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    total_cases: int
    passed_cases: int
    failed_cases: tuple[str, ...]
    results: tuple[GoldenCaseResult, ...]


def load_golden_cases(path: Path = DEFAULT_DATASET_PATH) -> tuple[GoldenCase, ...]:
    """Load a versioned JSON dataset and reject invalid or duplicate case IDs."""
    try:
        raw_cases = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid Golden dataset JSON: {path}") from error
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Golden dataset must contain a non-empty JSON array")

    cases: list[GoldenCase] = []
    case_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        try:
            case = GoldenCase.model_validate(raw_case)
        except ValidationError as error:
            raise ValueError(f"Invalid Golden case at index {index}") from error
        if case.id in case_ids:
            raise ValueError(f"Duplicate Golden case ID: {case.id}")
        case_ids.add(case.id)
        cases.append(case)

    known_ids = {case.id for case in cases}
    for case in cases:
        if case.equivalent_case_id and case.equivalent_case_id not in known_ids:
            raise ValueError(
                f"Golden case {case.id} references unknown equivalent_case_id "
                f"{case.equivalent_case_id}"
            )
    return tuple(cases)


def load_golden_artifacts(path: Path) -> dict[str, GoldenArtifact]:
    """Load externally supplied sanitized artifacts without accepting private payloads."""
    try:
        raw_artifacts = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid Golden artifact JSON: {path}") from error
    if not isinstance(raw_artifacts, dict):
        raise TypeError("Golden artifacts must be a JSON object keyed by case ID")
    artifacts: dict[str, GoldenArtifact] = {}
    for case_id, raw_artifact in raw_artifacts.items():
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Golden artifact IDs must be non-empty strings")
        try:
            artifacts[case_id] = GoldenArtifact.model_validate(raw_artifact)
        except ValidationError as error:
            raise ValueError(f"Invalid Golden artifact for case {case_id}") from error
    return artifacts


def evaluate_case(case: GoldenCase, artifact: GoldenArtifact) -> GoldenCaseResult:
    """Evaluate one case without inspecting private Agent or provider internals."""
    checks: list[GoldenCheck] = []
    actual_outcome = _outcome_for(artifact)
    _append_check(
        checks,
        name="outcome",
        expected=case.expected.outcome.value,
        actual=actual_outcome.value,
        passed=actual_outcome is case.expected.outcome,
        severity="critical" if case.expected.neutral_non_disclosure else "error",
    )
    _append_check(
        checks,
        name="response_language",
        expected=case.response_language,
        actual=artifact.response_language,
        passed=artifact.response_language == case.response_language,
    )
    if case.expected.expected_error_code is not None:
        _append_check(
            checks,
            name="error_code",
            expected=case.expected.expected_error_code,
            actual=artifact.error_code or "<none>",
            passed=artifact.error_code == case.expected.expected_error_code,
            severity="critical" if case.expected.neutral_non_disclosure else "error",
        )

    tool_names = tuple(call.tool for call in artifact.tool_calls)
    _append_check(
        checks,
        name="tool_count",
        expected=f"{case.expected.min_tool_calls}..{case.expected.max_tool_calls}",
        actual=str(len(tool_names)),
        passed=case.expected.min_tool_calls
        <= len(tool_names)
        <= case.expected.max_tool_calls,
    )
    _append_check(
        checks,
        name="expected_tools",
        expected=_format_values(case.expected.expected_tools),
        actual=_format_values(tool_names),
        passed=set(case.expected.expected_tools).issubset(tool_names),
    )
    if case.expected.allowed_tools:
        _append_check(
            checks,
            name="allowed_tools",
            expected=_format_values(case.expected.allowed_tools),
            actual=_format_values(tool_names),
            passed=set(tool_names).issubset(case.expected.allowed_tools),
        )
    _append_check(
        checks,
        name="forbidden_tools",
        expected=_format_values(case.expected.forbidden_tools),
        actual=_format_values(tool_names),
        passed=not set(tool_names).intersection(case.expected.forbidden_tools),
        severity="critical" if case.expected.neutral_non_disclosure else "error",
    )
    if case.expected.exact_tool_order:
        _append_check(
            checks,
            name="tool_order",
            expected=_format_values(case.expected.exact_tool_order),
            actual=_format_values(tool_names),
            passed=tool_names == case.expected.exact_tool_order,
        )

    identifier_values = tuple(identifier.value for identifier in artifact.identifiers)
    document_ids = tuple(document.document_id for document in artifact.documents)
    _append_presence_checks(
        checks,
        name="identifiers",
        expected=case.expected.expected_identifiers,
        forbidden=case.expected.forbidden_identifiers,
        actual=identifier_values,
        critical=case.expected.neutral_non_disclosure,
    )
    _append_presence_checks(
        checks,
        name="documents",
        expected=case.expected.expected_documents,
        forbidden=case.expected.forbidden_documents,
        actual=document_ids,
        critical=case.expected.neutral_non_disclosure,
    )

    normalized_answer = artifact.final_answer.casefold()
    _append_check(
        checks,
        name="required_observation_facts",
        expected=_format_values(case.expected.required_answer_facts),
        actual="present"
        if all(
            fact.casefold() in normalized_answer
            for fact in case.expected.required_answer_facts
        )
        else "missing",
        passed=all(
            fact.casefold() in normalized_answer
            for fact in case.expected.required_answer_facts
        ),
    )
    _append_check(
        checks,
        name="forbidden_claims",
        expected=_format_values(case.expected.forbidden_answer_claims),
        actual="none"
        if not any(
            claim.casefold() in normalized_answer
            for claim in case.expected.forbidden_answer_claims
        )
        else "forbidden claim present",
        passed=not any(
            claim.casefold() in normalized_answer
            for claim in case.expected.forbidden_answer_claims
        ),
    )
    _append_investigation_steps_check(checks, case, artifact, tool_names)
    _append_next_steps_check(checks, case, artifact)
    _append_non_disclosure_checks(checks, case, artifact)

    return GoldenCaseResult(
        case_id=case.id,
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
    )


def evaluate_cases(
    cases: Iterable[GoldenCase],
    artifacts: Mapping[str, GoldenArtifact],
    *,
    dataset: str = "golden",
) -> GoldenEvaluationReport:
    """Evaluate case artifacts and deterministic DE/EN parity pairs."""
    case_list = tuple(cases)
    results: dict[str, GoldenCaseResult] = {}
    for case in case_list:
        artifact = artifacts.get(case.id)
        if artifact is None:
            results[case.id] = GoldenCaseResult(
                case_id=case.id,
                passed=False,
                checks=(
                    GoldenCheck(
                        name="artifact_present",
                        passed=False,
                        expected="sanitized run artifact",
                        actual="missing",
                    ),
                ),
            )
            continue
        results[case.id] = evaluate_case(case, artifact)

    for case in case_list:
        if not case.equivalent_case_id:
            continue
        reference = artifacts.get(case.equivalent_case_id)
        artifact = artifacts.get(case.id)
        if reference is None or artifact is None:
            continue
        parity_check = GoldenCheck(
            name="language_parity",
            passed=_parity_projection(reference) == _parity_projection(artifact),
            expected="same outcome, tool trajectory, identifiers, and documents",
            actual="same"
            if _parity_projection(reference) == _parity_projection(artifact)
            else "different",
        )
        result = results[case.id]
        checks = (*result.checks, parity_check)
        results[case.id] = result.model_copy(
            update={"checks": checks, "passed": all(check.passed for check in checks)}
        )

    ordered_results = tuple(results[case.id] for case in case_list)
    return GoldenEvaluationReport(
        dataset=dataset,
        total_cases=len(ordered_results),
        passed_cases=sum(result.passed for result in ordered_results),
        failed_cases=tuple(
            result.case_id for result in ordered_results if not result.passed
        ),
        results=ordered_results,
    )


def _outcome_for(artifact: GoldenArtifact) -> GoldenOutcome:
    if artifact.status == "denied":
        return GoldenOutcome.EXPECTED_NON_DISCLOSURE
    if artifact.status == "success":
        return GoldenOutcome.SUCCESS
    classified = classify_run_outcome(
        status="failed",
        error_code=artifact.error_code,
        provider_error_code=artifact.provider_error_code,
    )
    return (
        GoldenOutcome.BLOCKED_BY_PROVIDER
        if classified is AcceptanceOutcome.BLOCKED_BY_PROVIDER
        else GoldenOutcome.FAIL
    )


def _append_presence_checks(
    checks: list[GoldenCheck],
    *,
    name: str,
    expected: tuple[str, ...],
    forbidden: tuple[str, ...],
    actual: tuple[str, ...],
    critical: bool,
) -> None:
    _append_check(
        checks,
        name=f"expected_{name}",
        expected=_format_values(expected),
        actual=_format_values(actual),
        passed=set(expected).issubset(actual),
    )
    _append_check(
        checks,
        name=f"forbidden_{name}",
        expected=_format_values(forbidden),
        actual=_format_values(actual),
        passed=not set(forbidden).intersection(actual),
        severity="critical" if critical else "error",
    )


def _append_investigation_steps_check(
    checks: list[GoldenCheck],
    case: GoldenCase,
    artifact: GoldenArtifact,
    tool_names: tuple[str, ...],
) -> None:
    if not case.expected.require_investigation_steps:
        return
    actions = tuple(step.action for step in artifact.investigation_steps)
    step_numbers = tuple(step.step for step in artifact.investigation_steps)
    _append_check(
        checks,
        name="investigation_steps",
        expected="one ordered step for every admitted tool call",
        actual=_format_values(actions),
        passed=(
            actions == tool_names
            and step_numbers == tuple(range(1, len(tool_names) + 1))
        ),
    )


def _append_next_steps_check(
    checks: list[GoldenCheck],
    case: GoldenCase,
    artifact: GoldenArtifact,
) -> None:
    valid = len(artifact.next_steps) <= case.expected.max_next_steps and all(
        step.strip() for step in artifact.next_steps
    )
    protected_references = (
        *case.expected.forbidden_identifiers,
        *case.expected.forbidden_documents,
    )
    valid = valid and not any(
        protected.casefold() in step.casefold()
        for step in artifact.next_steps
        for protected in protected_references
    )
    if case.expected.require_next_steps:
        valid = valid and bool(artifact.next_steps)
    _append_check(
        checks,
        name="next_steps",
        expected=(
            f"1..{case.expected.max_next_steps} non-empty values"
            if case.expected.require_next_steps
            else f"0..{case.expected.max_next_steps} non-empty values"
        ),
        actual=str(len(artifact.next_steps)),
        passed=valid,
    )


def _append_non_disclosure_checks(
    checks: list[GoldenCheck],
    case: GoldenCase,
    artifact: GoldenArtifact,
) -> None:
    if not case.expected.neutral_non_disclosure:
        return
    protected_values = (
        *case.expected.forbidden_identifiers,
        *case.expected.forbidden_documents,
    )
    answer_leaks = any(
        protected.casefold() in artifact.final_answer.casefold()
        for protected in protected_values
    )
    _append_check(
        checks,
        name="neutral_non_disclosure",
        expected="no model/tool execution or protected artifact disclosure",
        actual=(
            "leak"
            if answer_leaks
            or artifact.tool_calls
            or artifact.identifiers
            or artifact.documents
            else "neutral"
        ),
        passed=not (
            answer_leaks
            or artifact.tool_calls
            or artifact.investigation_steps
            or artifact.identifiers
            or artifact.documents
        ),
        severity="critical",
    )


def _append_check(
    checks: list[GoldenCheck],
    *,
    name: str,
    expected: str,
    actual: str,
    passed: bool,
    severity: Literal["critical", "error"] = "error",
) -> None:
    checks.append(
        GoldenCheck(
            name=name,
            passed=passed,
            expected=expected,
            actual=actual,
            severity=severity,
        )
    )


def _parity_projection(artifact: GoldenArtifact) -> tuple[object, ...]:
    return (
        _outcome_for(artifact),
        tuple(call.tool for call in artifact.tool_calls),
        tuple(identifier.value for identifier in artifact.identifiers),
        tuple(document.document_id for document in artifact.documents),
    )


def _format_values(values: Iterable[str]) -> str:
    return ", ".join(values) or "<none>"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate or deterministically evaluate versioned Golden contracts."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument(
        "--artifacts",
        type=Path,
        help="Optional sanitized JSON artifact map keyed by Golden case ID.",
    )
    args = parser.parse_args()
    cases = load_golden_cases(args.dataset)
    if args.artifacts is None:
        print(f"Validated {len(cases)} Golden cases from {args.dataset}")
        return
    report = evaluate_cases(
        cases,
        load_golden_artifacts(args.artifacts),
        dataset=args.dataset.name,
    )
    print(report.model_dump_json(indent=2))
    if report.failed_cases:
        raise SystemExit(1)
