import asyncio
from uuid import uuid4

import pytest

from industrial_ai_agent.agent.run_classification_policy import (
    INTERNAL_DIAGNOSTIC_TOOLS,
    AgentRunClassificationPolicy,
    AgentRunProfile,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore


def test_internal_diagnostic_policy_is_internal_and_strictly_read_only() -> None:
    policy = AgentRunClassificationPolicy().resolve(AgentRunProfile.INTERNAL_DIAGNOSTIC)

    assert policy.data_classification is DataClassification.INTERNAL
    assert policy.mcp_clearance_ceiling is DataClassification.INTERNAL
    assert policy.allowed_tool_names == INTERNAL_DIAGNOSTIC_TOOLS
    assert "create_maintenance_ticket" not in policy.allowed_tool_names
    assert policy.mcp_client_identity == "industrial-agent-internal"


def test_persisted_policy_rejects_classification_mismatch() -> None:
    with pytest.raises(ValueError, match="classification"):
        AgentRunClassificationPolicy().resolve_persisted(
            profile=AgentRunProfile.INTERNAL_DIAGNOSTIC,
            data_classification=DataClassification.CONFIDENTIAL,
        )


def test_persisted_run_policy_cannot_change_during_execution() -> None:
    async def exercise() -> None:
        store = InMemoryAgentRunStore()
        run_id = uuid4()
        await store.create(
            run_id,
            data_classification=DataClassification.INTERNAL,
            run_profile=AgentRunProfile.INTERNAL_DIAGNOSTIC,
        )

        with pytest.raises(ValueError, match="classification"):
            await store.bind_execution_context(
                run_id,
                data_classification=DataClassification.CONFIDENTIAL,
                run_profile=AgentRunProfile.INTERNAL_DIAGNOSTIC,
                model_profile="troubleshooting",
            )
        with pytest.raises(ValueError, match="profile"):
            await store.bind_execution_context(
                run_id,
                data_classification=DataClassification.INTERNAL,
                run_profile=AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
                model_profile="troubleshooting",
            )

    asyncio.run(exercise())
