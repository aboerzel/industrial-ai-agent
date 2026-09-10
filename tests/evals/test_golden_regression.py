from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.golden.runner import (
    DEFAULT_DATASET_PATH,
    GoldenArtifact,
    GoldenCase,
    GoldenOutcome,
    evaluate_case,
    evaluate_cases,
    load_golden_artifacts,
    load_golden_cases,
)
from industrial_ai_agent.agent.agent_run import (
    DocumentReference,
    ExecutedToolCall,
    IdentifierReference,
    IdentifierType,
    InvestigationStep,
)


def _identifier(value: str) -> IdentifierReference:
    if value.startswith("MT-"):
        identifier_type = IdentifierType.MAINTENANCE_TICKET
    elif value.startswith("P") and value[1:].isdigit():
        identifier_type = IdentifierType.PRODUCT
    elif value.startswith("S") and value[1:].isdigit():
        identifier_type = IdentifierType.STATION
    else:
        identifier_type = IdentifierType.ERROR_CODE
    return IdentifierReference(value=value, type=identifier_type)


def _passing_artifact(case: GoldenCase) -> GoldenArtifact:
    expected = case.expected
    if expected.outcome is GoldenOutcome.EXPECTED_NON_DISCLOSURE:
        return GoldenArtifact(
            status="denied",
            response_language=case.response_language,
            final_answer="Requested information is unavailable.",
            error_code=expected.expected_error_code,
        )
    if expected.outcome is GoldenOutcome.BLOCKED_BY_PROVIDER:
        return GoldenArtifact(
            status="failed",
            response_language=case.response_language,
            error_code=expected.expected_error_code,
        )
    if expected.outcome is GoldenOutcome.FAIL:
        return GoldenArtifact(
            status="failed",
            response_language=case.response_language,
            error_code=expected.expected_error_code,
        )

    tools = tuple(
        ExecutedToolCall(tool=tool, arguments={})
        for tool in expected.exact_tool_order or expected.expected_tools
    )
    return GoldenArtifact(
        status="success",
        response_language=case.response_language,
        final_answer=" ".join(expected.required_answer_facts) or "Authorized result.",
        tool_calls=tools,
        investigation_steps=tuple(
            InvestigationStep(
                step=index,
                action=tool.tool,
                finding="Authorized deterministic observation.",
            )
            for index, tool in enumerate(tools, start=1)
        ),
        identifiers=tuple(
            _identifier(value) for value in expected.expected_identifiers
        ),
        documents=tuple(
            DocumentReference(
                document_id=document_id,
                title="Authorized technical document",
                format="markdown",
            )
            for document_id in expected.expected_documents
        ),
    )


def test_v1_dataset_is_versioned_and_covers_trust_boundaries() -> None:
    cases = load_golden_cases()

    assert DEFAULT_DATASET_PATH.name == "cases.json"
    assert len(cases) == 15
    assert len({case.id for case in cases}) == len(cases)
    tags = {tag for case in cases for tag in case.tags}
    assert {
        "public",
        "confidential",
        "non-disclosure",
        "cross-source",
        "provider",
    } <= tags
    assert any(case.equivalent_case_id for case in cases)


def test_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    raw_case = {
        "id": "duplicate",
        "title": "Duplicate",
        "request": "Request",
        "response_language": "EN",
        "clearance": "PUBLIC",
        "expected": {"outcome": "success"},
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([raw_case, raw_case]), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate Golden case ID"):
        load_golden_cases(path)


def test_dataset_rejects_malformed_case(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "invalid",
                    "title": "Invalid",
                    "request": "Request",
                    "response_language": "EN",
                    "clearance": "PUBLIC",
                    "expected": {
                        "outcome": "success",
                        "min_tool_calls": 2,
                        "max_tool_calls": 1,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid Golden case"):
        load_golden_cases(path)


def test_artifact_loader_rejects_private_or_malformed_shape(tmp_path: Path) -> None:
    path = tmp_path / "artifacts.json"
    path.write_text(
        json.dumps(
            {
                "public-station-s01-de": {
                    "status": "success",
                    "response_language": "DE",
                    "raw_provider_response": "must not be accepted",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid Golden artifact"):
        load_golden_artifacts(path)


def test_default_golden_suite_passes_with_deterministic_authorized_artifacts() -> None:
    cases = load_golden_cases()

    report = evaluate_cases(
        cases,
        {case.id: _passing_artifact(case) for case in cases},
        dataset="golden-v1-fake-artifacts",
    )

    assert report.total_cases == 15
    assert report.passed_cases == 15
    assert report.failed_cases == ()


def test_expected_and_forbidden_tool_checks_are_attributable() -> None:
    case = next(
        case for case in load_golden_cases() if case.id == "public-station-s01-de"
    )
    artifact = _passing_artifact(case).model_copy(
        update={
            "tool_calls": (ExecutedToolCall(tool="get_product_history", arguments={}),)
        }
    )

    result = evaluate_case(case, artifact)

    assert result.passed is False
    assert any(
        check.name == "expected_tools" and check.passed is False
        for check in result.checks
    )
    assert any(
        check.name == "allowed_tools" and check.passed is False
        for check in result.checks
    )


def test_identifier_and_document_checks_reject_unexpected_or_missing_references() -> (
    None
):
    case = next(
        case
        for case in load_golden_cases()
        if case.id == "confidential-quality-09-document"
    )
    artifact = _passing_artifact(case).model_copy(
        update={
            "identifiers": (_identifier("QUALITY-09"), _identifier("P9001")),
            "documents": (),
        }
    )

    result = evaluate_case(case, artifact)

    assert result.passed is False
    assert any(
        check.name == "expected_documents" and check.passed is False
        for check in result.checks
    )
    assert any(
        check.name == "forbidden_identifiers" and check.passed is False
        for check in result.checks
    )


def test_non_disclosure_is_a_critical_gate_and_rejects_a_hidden_identifier() -> None:
    case = next(
        case
        for case in load_golden_cases()
        if case.id == "internal-p4711-nondisclosure"
    )
    artifact = _passing_artifact(case).model_copy(
        update={
            "final_answer": "P4711 requires CONFIDENTIAL clearance.",
            "identifiers": (_identifier("P4711"),),
        }
    )

    result = evaluate_case(case, artifact)

    assert result.passed is False
    assert any(
        check.name == "neutral_non_disclosure"
        and check.passed is False
        and check.severity == "critical"
        for check in result.checks
    )


def test_non_disclosure_rejects_a_protected_reference_in_next_steps() -> None:
    case = next(
        case
        for case in load_golden_cases()
        if case.id == "internal-p4711-nondisclosure"
    )
    artifact = _passing_artifact(case).model_copy(
        update={"next_steps": ("Investigate P4711 at S04.",)}
    )

    result = evaluate_case(case, artifact)

    assert result.passed is False
    assert any(
        check.name == "next_steps" and check.passed is False for check in result.checks
    )


def test_known_contradictory_claim_is_rejected_without_exact_answer_matching() -> None:
    case = next(
        case
        for case in load_golden_cases()
        if case.id == "confidential-p4711-history-en"
    )
    artifact = _passing_artifact(case).model_copy(
        update={
            "final_answer": (
                "P4711 POSITION-ENC-02 QUALITY-09 FAILED. "
                "P4711 successfully passed S04."
            )
        }
    )

    result = evaluate_case(case, artifact)

    assert result.passed is False
    assert any(
        check.name == "forbidden_claims" and check.passed is False
        for check in result.checks
    )


@pytest.mark.parametrize(
    ("case_id", "expected_outcome"),
    (
        ("provider-rate-limit", GoldenOutcome.BLOCKED_BY_PROVIDER),
        ("provider-quota", GoldenOutcome.BLOCKED_BY_PROVIDER),
        ("provider-unavailable", GoldenOutcome.BLOCKED_BY_PROVIDER),
        ("execution-timeout", GoldenOutcome.FAIL),
    ),
)
def test_failure_classification_contracts(
    case_id: str, expected_outcome: GoldenOutcome
) -> None:
    case = next(case for case in load_golden_cases() if case.id == case_id)

    result = evaluate_case(case, _passing_artifact(case))

    assert result.passed is True
    assert (
        next(check for check in result.checks if check.name == "outcome").actual
        == expected_outcome.value
    )


def test_de_en_parity_rejects_a_changed_authorized_trajectory() -> None:
    cases = load_golden_cases()
    artifacts = {case.id: _passing_artifact(case) for case in cases}
    artifacts["confidential-p4711-history-en"] = artifacts[
        "confidential-p4711-history-en"
    ].model_copy(
        update={
            "tool_calls": (ExecutedToolCall(tool="get_machine_status", arguments={}),),
            "investigation_steps": (
                InvestigationStep(
                    step=1,
                    action="get_machine_status",
                    finding="Authorized deterministic observation.",
                ),
            ),
        }
    )

    report = evaluate_cases(cases, artifacts)
    result = next(
        item
        for item in report.results
        if item.case_id == "confidential-p4711-history-en"
    )

    assert result.passed is False
    assert any(
        check.name == "language_parity" and check.passed is False
        for check in result.checks
    )
