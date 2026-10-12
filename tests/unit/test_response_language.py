import asyncio
from uuid import uuid4

import pytest

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
from industrial_ai_agent.agent.response_language import (
    DetectedResponseLanguage,
    ResponseLanguage,
    detect_response_language,
    is_response_language_compliant,
    user_facing_error_message,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.lingua_response_language_detector import (
    LinguaResponseLanguageDetector,
)


_DETECTOR = LinguaResponseLanguageDetector()


@pytest.mark.parametrize(
    ("user_message", "expected"),
    (
        (
            "Untersuche, warum Produkt P4711 an Station S04 fehlgeschlagen ist.",
            ResponseLanguage.DE,
        ),
        ("Welche Stationen sind verfügbar?", ResponseLanguage.DE),
        ("zeige mir das ticket MT-6EA0DEF5515A", ResponseLanguage.DE),
        (
            "Investigate why product P4711 failed at station S04.",
            ResponseLanguage.EN,
        ),
        ("Which stations are available?", ResponseLanguage.EN),
        ("P4711 S04?", ResponseLanguage.EN),
        ("status P4711", ResponseLanguage.EN),
    ),
)
def test_detect_response_language_uses_a_stable_english_fallback(
    user_message: str, expected: ResponseLanguage
) -> None:
    assert detect_response_language(user_message) is expected


@pytest.mark.parametrize(
    ("text", "selected_language", "expected"),
    (
        (
            "Ich kenne folgende Stationen. Beide Stationen sind aktuell in Betrieb.",
            ResponseLanguage.EN,
            False,
        ),
        (
            "I know the following stations. Both stations are currently operating.",
            ResponseLanguage.EN,
            True,
        ),
        (
            "S04 needs further investigation.",
            ResponseLanguage.DE,
            False,
        ),
        (
            "S04 benötigt weitere Untersuchung.",
            ResponseLanguage.DE,
            True,
        ),
        ("S04: RUNNING", ResponseLanguage.EN, True),
        ("Station S04 ist RUNNING.", ResponseLanguage.EN, False),
        ("Please inspect S04 immediately.", ResponseLanguage.DE, False),
        ("Please inspect S04 immediately.", ResponseLanguage.EN, True),
        ("Bitte kontrolliere S04 sofort.", ResponseLanguage.EN, False),
        ("Bitte kontrolliere S04 sofort.", ResponseLanguage.DE, True),
        ("The station ist RUNNING.", ResponseLanguage.EN, False),
        ("The station mit QUALITY-09.", ResponseLanguage.EN, False),
        ("Munich is running.", ResponseLanguage.EN, True),
        ("Gerät geprüft.", ResponseLanguage.DE, True),
        ("`MÜNCHEN-01`: RUNNING", ResponseLanguage.EN, True),
        ("MÜNCHEN-ID: RUNNING", ResponseLanguage.EN, True),
        ("get_machine_status: RUNNING", ResponseLanguage.DE, True),
        ("Veuillez inspecter S04 immédiatement.", ResponseLanguage.EN, False),
        ("No funciona S04.", ResponseLanguage.EN, False),
        ("The estación S04 está activa.", ResponseLanguage.EN, False),
        ("Проверьте станцию S04.", ResponseLanguage.DE, False),
        ("```text\nIch kenne die Station S04.\n```", ResponseLanguage.EN, False),
        ("```text\nIch kenne die Station S04.\n```", ResponseLanguage.DE, True),
        (
            "### Likely Root Cause\n\nDie Station meldet einen Qualitätsfehler.",
            ResponseLanguage.DE,
            True,
        ),
        ("**Ich kenne die Station S04.**", ResponseLanguage.EN, False),
        ("DIE STATION IST AKTIV.", ResponseLanguage.EN, False),
        ("DIE1 STATION2 IST3 JETZT4 AKTIV5.", ResponseLanguage.EN, False),
        ("... !!!", ResponseLanguage.EN, False),
        ("https://example.invalid/S04", ResponseLanguage.EN, True),
    ),
)
def test_response_language_compliance_is_fail_closed_with_technical_exceptions(
    text: str, selected_language: ResponseLanguage, expected: bool
) -> None:
    assert (
        is_response_language_compliant(text, selected_language, _DETECTOR) is expected
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        (
            "The authorized investigation is complete and the station is operational.",
            DetectedResponseLanguage.EN,
        ),
        (
            "Die autorisierte Untersuchung ist abgeschlossen und die Station ist "
            "betriebsbereit.",
            DetectedResponseLanguage.DE,
        ),
        (
            "Veuillez contrôler immédiatement la station concernée.",
            DetectedResponseLanguage.OTHER,
        ),
    ),
)
def test_lingua_adapter_identifies_supported_and_unsupported_prose(
    text: str, expected: DetectedResponseLanguage
) -> None:
    assert _DETECTOR.detect(text) is expected


def test_run_store_preserves_response_language_across_approval_lifecycle() -> None:
    async def exercise() -> None:
        store = InMemoryAgentRunStore()
        run_id = uuid4()
        await store.create(
            run_id,
            request_text="Erstelle ein Wartungsticket für S04.",
            data_classification=DataClassification.CONFIDENTIAL,
            response_language=ResponseLanguage.DE,
        )
        await store.wait_for_approval(run_id, {"action": "create_maintenance_ticket"})
        claimed = await store.claim_resume(
            run_id,
            decision="approve",
            approval_clearance=DataClassification.CONFIDENTIAL,
        )
        assert claimed is not None
        completed = await store.complete(
            run_id,
            AgentRunResult(
                status=AgentRunStatus.SUCCESS,
                final_answer="Das Wartungsticket wurde erstellt.",
                tool_call_count=0,
            ),
        )
        assert completed.response_language is ResponseLanguage.DE

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "error_code",
    (
        "llm_rate_limit",
        "llm_provider_unavailable",
        "llm_provider_request_invalid",
        "model_output_invalid",
        "internal_error",
        "agent_execution_timeout",
        "mcp_service_unavailable",
        "tool_execution_failed",
        "model_capability_mismatch",
        "model_not_configured",
        "evidence_requirements_unsatisfied",
        "evidence_source_unavailable",
        "requested_data_unavailable",
        "recovery_blocked",
        "recovery_failed",
        "recovery_succeeded",
    ),
)
def test_public_error_messages_are_localized_for_both_supported_languages(
    error_code: str,
) -> None:
    german = user_facing_error_message(error_code, ResponseLanguage.DE)
    english = user_facing_error_message(error_code, ResponseLanguage.EN)

    assert german != english
    assert german.endswith(".")
    assert english.endswith(".")
