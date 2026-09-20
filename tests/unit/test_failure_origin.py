import asyncio
from uuid import uuid4

import pytest

from industrial_ai_agent.agent.failure_origin import FailureOrigin
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore


@pytest.mark.parametrize(
    ("error_code", "expected_origin"),
    (
        ("model_not_configured", FailureOrigin.MODEL_SELECTION),
        ("model_capability_mismatch", FailureOrigin.CAPABILITY_VALIDATION),
        ("model_egress_denied", FailureOrigin.SECURITY_POLICY),
        ("llm_rate_limit", FailureOrigin.PROVIDER_RATE_LIMIT),
        ("llm_provider_unavailable", FailureOrigin.PROVIDER_CONNECTION),
        ("llm_provider_request_invalid", FailureOrigin.PROVIDER_REQUEST),
        ("mcp_service_unavailable", FailureOrigin.MCP),
        ("evidence_source_unavailable", FailureOrigin.ORCHESTRATION),
        ("model_output_invalid", FailureOrigin.MODEL_OUTPUT_VALIDATION),
    ),
)
def test_persisted_failures_have_a_coarse_stable_origin(
    error_code: str, expected_origin: FailureOrigin
) -> None:
    async def exercise() -> None:
        store = InMemoryAgentRunStore()
        run_id = uuid4()
        await store.create(run_id, data_classification=DataClassification.CONFIDENTIAL)
        failed = await store.fail(run_id, error_code)

        assert failed.error_code == error_code
        assert failed.failure_origin is expected_origin

    asyncio.run(exercise())


def test_successful_run_has_no_failure_origin() -> None:
    async def exercise() -> None:
        store = InMemoryAgentRunStore()
        run_id = uuid4()
        created = await store.create(run_id)

        assert created.failure_origin is None

    asyncio.run(exercise())
