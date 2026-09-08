import asyncio
from uuid import uuid4

import pytest

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
from industrial_ai_agent.agent.response_language import (
    ResponseLanguage,
    detect_response_language,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore


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
        claimed = await store.claim_resume(run_id, decision="approve")
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
