import asyncio
from uuid import uuid4

import pytest

from industrial_ai_agent.agent.run_classification_policy import (
    INTERNAL_DIAGNOSTIC_TOOLS,
    AgentRunClassificationPolicy,
    AgentRunProfile,
    resolve_demo_run_profile,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore


def test_internal_diagnostic_policy_is_internal_and_strictly_read_only() -> None:
    policy = AgentRunClassificationPolicy().resolve(AgentRunProfile.INTERNAL_DIAGNOSTIC)

    assert policy.data_classification is DataClassification.INTERNAL
    assert policy.mcp_clearance_ceiling is DataClassification.INTERNAL
    assert policy.allowed_tool_names == INTERNAL_DIAGNOSTIC_TOOLS
    assert "create_maintenance_ticket" not in policy.allowed_tool_names
    assert policy.mcp_client_identity == "industrial-agent-internal"


def test_restricted_user_keeps_confidential_run_at_confidential_data_ceiling() -> None:
    restricted_user = SecurityContext(
        subject_id="restricted-demo-user",
        roles=("demo-engineer",),
        clearance=DataClassification.RESTRICTED,
        authenticated=True,
    )

    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        security_context=restricted_user,
    )

    assert policy.data_classification is DataClassification.CONFIDENTIAL
    assert policy.mcp_clearance_ceiling is DataClassification.CONFIDENTIAL
    assert policy.mcp_client_identity == "industrial-agent"


def test_discovery_uses_server_resolved_user_clearance_without_broadening_named_case() -> (
    None
):
    restricted_user = SecurityContext(
        subject_id="restricted-discovery-user",
        roles=("demo-engineer",),
        clearance=DataClassification.RESTRICTED,
        authenticated=True,
    )

    discovery_profile = resolve_demo_run_profile(
        "Which stations are available?", security_context=restricted_user
    )
    named_profile = resolve_demo_run_profile(
        "Investigate P4711 at S04.", security_context=restricted_user
    )

    assert discovery_profile is AgentRunProfile.RESTRICTED_TROUBLESHOOTING
    assert named_profile is AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING


@pytest.mark.parametrize(
    "message",
    (
        "Why did the last batch fail?",
        "Please export the customer production plan.",
        "  WhY did the last batch fail?  ",
    ),
)
def test_unknown_free_text_is_conservatively_restricted(message: str) -> None:
    assert (
        resolve_demo_run_profile(message) is AgentRunProfile.RESTRICTED_TROUBLESHOOTING
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("Investigate P4711 at S04.", AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING),
        ("Investigate P9001 at S07.", AgentRunProfile.RESTRICTED_TROUBLESHOOTING),
    ),
)
def test_named_demo_cases_keep_their_deterministic_classification(
    message: str, expected: AgentRunProfile
) -> None:
    assert resolve_demo_run_profile(message) is expected


def test_known_public_discovery_request_stays_public() -> None:
    public_user = SecurityContext(
        subject_id="public-demo-user",
        roles=("demo-engineer",),
        clearance=DataClassification.PUBLIC,
        authenticated=True,
    )

    assert (
        resolve_demo_run_profile(
            "Which stations are available?", security_context=public_user
        )
        is AgentRunProfile.PUBLIC_INFORMATION
    )


def test_known_internal_discovery_request_stays_internal() -> None:
    internal_user = SecurityContext(
        subject_id="internal-demo-user",
        roles=("demo-engineer",),
        clearance=DataClassification.INTERNAL,
        authenticated=True,
    )

    assert (
        resolve_demo_run_profile(
            "Which stations are available?", security_context=internal_user
        )
        is AgentRunProfile.INTERNAL_DIAGNOSTIC
    )


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
