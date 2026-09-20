from evals.real_model_quality import (
    DetectedLanguage,
    QualityCheck,
    QualityScenario,
    RealModelRunArtifact,
    TechnicalHealth,
    ToolTrajectoryQuality,
    annotate_repeatability,
    detect_output_artifacts,
    detect_output_language,
    evaluate_real_model_run,
)
from industrial_ai_agent.agent.agent_run import (
    AgentRunStatus,
    ExecutedToolCall,
    IdentifierReference,
    IdentifierType,
)
from industrial_ai_agent.agent.failure_origin import FailureOrigin

S04 = QualityScenario(
    scenario_id="s04_quality_09",
    required_tools=("get_machine_status", "search_documentation"),
    allowed_tools=("get_machine_status", "search_documentation"),
    required_identifiers=("S04", "QUALITY-09"),
    required_reference_fault_ids=("QUALITY-09",),
)


def good_artifact(**changes: object) -> RealModelRunArtifact:
    values: dict[str, object] = {
        "run_id": "run-1",
        "model_id": "local_quality",
        "status": AgentRunStatus.SUCCESS,
        "final_answer": "Station S04 ist FAULTED mit QUALITY-09. Die Dokumentation empfiehlt eine Prüfung.",
        "tool_calls": (
            ExecutedToolCall(
                tool="get_machine_status", arguments={"station_id": "S04"}
            ),
            ExecutedToolCall(
                tool="search_documentation", arguments={"query": "QUALITY-09"}
            ),
        ),
        "identifiers": (
            IdentifierReference(value="S04", type=IdentifierType.STATION),
            IdentifierReference(value="QUALITY-09", type=IdentifierType.ERROR_CODE),
        ),
        "trusted_reference_fault_ids": ("QUALITY-09",),
        "next_steps": ("Prüfen Sie die Qualitätsmessung gemäß der Dokumentation.",),
    }
    values.update(changes)
    return RealModelRunArtifact.model_validate(values)


def test_technical_failure_is_excluded_from_quality_metrics() -> None:
    result = evaluate_real_model_run(
        S04, good_artifact(failure_origin=FailureOrigin.PROVIDER_CONNECTION)
    )
    assert result.infrastructure_health is TechnicalHealth.TECHNICAL_FAILURE
    assert result.grounding.result is QualityCheck.NOT_EVALUATED
    assert result.language_compliance.result is QualityCheck.NOT_EVALUATED


def test_missing_final_answer_does_not_count_as_language_failure() -> None:
    result = evaluate_real_model_run(S04, good_artifact(final_answer=""))

    assert result.infrastructure_health is TechnicalHealth.HEALTHY
    assert result.language_compliance.result is QualityCheck.NOT_EVALUATED


def test_clean_s04_result_passes_deterministic_contract() -> None:
    result = evaluate_real_model_run(S04, good_artifact())
    assert result.tool_trajectory is ToolTrajectoryQuality.COMPLETE
    assert result.grounding.result is QualityCheck.PASS
    assert result.reference_relevance.result is QualityCheck.PASS
    assert result.language_compliance.result is QualityCheck.PASS
    assert result.output_cleanliness.result is QualityCheck.PASS


def test_trusted_fault_provenance_satisfies_reference_relevance() -> None:
    result = evaluate_real_model_run(
        S04, good_artifact(trusted_reference_fault_ids=("QUALITY-09",))
    )

    assert result.reference_relevance.result is QualityCheck.PASS


def test_unrelated_fault_provenance_does_not_satisfy_reference_relevance() -> None:
    result = evaluate_real_model_run(
        S04, good_artifact(trusted_reference_fault_ids=("POSITION-02",))
    )

    assert result.reference_relevance.result is QualityCheck.FAIL


def test_query_text_cannot_satisfy_reference_relevance() -> None:
    result = evaluate_real_model_run(
        S04,
        good_artifact(
            tool_calls=(
                ExecutedToolCall(
                    tool="get_machine_status", arguments={"station_id": "S04"}
                ),
                ExecutedToolCall(
                    tool="search_documentation", arguments={"query": "QUALITY-09"}
                ),
            ),
            trusted_reference_fault_ids=(),
        ),
    )

    assert result.reference_relevance.result is QualityCheck.FAIL


def test_document_body_text_cannot_satisfy_reference_relevance() -> None:
    result = evaluate_real_model_run(
        S04,
        good_artifact(
            final_answer="QUALITY-09 appears only in untrusted document body text.",
            trusted_reference_fault_ids=(),
        ),
    )

    assert result.reference_relevance.result is QualityCheck.FAIL


def test_one_relevant_trusted_document_among_multiple_faults_is_sufficient() -> None:
    result = evaluate_real_model_run(
        S04,
        good_artifact(
            trusted_reference_fault_ids=("POSITION-02", "QUALITY-09"),
        ),
    )

    assert result.reference_relevance.result is QualityCheck.PASS


def test_optional_next_steps_do_not_fail_the_quality_contract() -> None:
    result = evaluate_real_model_run(S04, good_artifact(next_steps=()))

    assert result.next_step_usefulness.result is QualityCheck.PASS


def test_missing_required_tool_is_incomplete() -> None:
    result = evaluate_real_model_run(S04, good_artifact(tool_calls=()))
    assert result.tool_trajectory is ToolTrajectoryQuality.INCOMPLETE
    assert result.tool_use_correctness.result is QualityCheck.FAIL


def test_fabricated_identifier_is_rejected_when_forbidden_by_the_scenario() -> None:
    scenario = S04.model_copy(update={"forbidden_identifiers": ("POSITION-ENC-02",)})
    result = evaluate_real_model_run(
        scenario,
        good_artifact(
            identifiers=(
                IdentifierReference(value="S04", type=IdentifierType.STATION),
                IdentifierReference(value="QUALITY-09", type=IdentifierType.ERROR_CODE),
                IdentifierReference(
                    value="POSITION-ENC-02", type=IdentifierType.ERROR_CODE
                ),
            )
        ),
    )
    assert result.grounding.result is QualityCheck.FAIL


def test_repeated_tool_call_is_reported_as_redundant() -> None:
    status = ExecutedToolCall(
        tool="get_machine_status", arguments={"station_id": "S04"}
    )
    result = evaluate_real_model_run(
        S04,
        good_artifact(
            tool_calls=(
                status,
                status,
                ExecutedToolCall(
                    tool="search_documentation", arguments={"query": "QUALITY-09"}
                ),
            )
        ),
    )
    assert result.tool_trajectory is ToolTrajectoryQuality.REDUNDANT


def test_language_detector_handles_german_english_han_and_mixed() -> None:
    assert (
        detect_output_language("Die Station ist fehlerhaft und wird geprüft.")
        is DetectedLanguage.GERMAN
    )
    assert (
        detect_output_language("The station is active and the next steps are clear.")
        is DetectedLanguage.ENGLISH
    )
    assert detect_output_language("站点 S04 出现错误") is DetectedLanguage.CHINESE
    assert (
        detect_output_language("Die station is active und the next steps.")
        is DetectedLanguage.MIXED
    )


def test_technical_identifiers_do_not_create_language_mismatch() -> None:
    assert (
        detect_output_language("Station S04 ist mit QUALITY-09 fehlerhaft.")
        is DetectedLanguage.GERMAN
    )


def test_unresolved_template_artifacts_fail_cleanliness() -> None:
    assert "python_mapping_placeholder" in detect_output_artifacts(
        "Status: {data['status']}"
    )
    result = evaluate_real_model_run(
        S04, good_artifact(final_answer="Status: {data['status']}")
    )
    assert result.output_cleanliness.result is QualityCheck.FAIL


def test_next_steps_cannot_claim_an_unauthorized_executed_action() -> None:
    result = evaluate_real_model_run(
        S04,
        good_artifact(next_steps=("Neustart wurde bereits ohne Freigabe ausgeführt.",)),
    )
    assert result.next_step_usefulness.result is QualityCheck.FAIL


def test_repeatability_compares_outcomes_not_exact_prose() -> None:
    first = evaluate_real_model_run(S04, good_artifact(run_id="one"))
    second = evaluate_real_model_run(
        S04,
        good_artifact(
            run_id="two",
            final_answer="S04 ist FAULTED mit QUALITY-09. Die Dokumentation fordert eine Prüfung.",
        ),
    )
    annotated = annotate_repeatability((first, second))
    assert all(result.repeatability.result is QualityCheck.PASS for result in annotated)
