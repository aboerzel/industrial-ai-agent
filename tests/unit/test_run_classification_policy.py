import asyncio
from uuid import uuid4

import pytest

from industrial_ai_agent.agent.run_classification_policy import (
    INTERNAL_DIAGNOSTIC_TOOLS,
    PUBLIC_INFORMATION_TOOLS,
    RESTRICTED_INFORMATION_TOOLS,
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


def test_public_information_policy_allows_rls_filtered_product_history() -> None:
    policy = AgentRunClassificationPolicy().resolve(AgentRunProfile.PUBLIC_INFORMATION)

    assert policy.allowed_tool_names == PUBLIC_INFORMATION_TOOLS
    assert "get_product_history" in policy.allowed_tool_names


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

    assert discovery_profile is AgentRunProfile.RESTRICTED_INFORMATION
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


def test_restricted_station_status_uses_local_information_requirements() -> None:
    context = SecurityContext(
        subject_id="restricted-station-status",
        roles=("demo-engineer",),
        clearance=DataClassification.RESTRICTED,
        authenticated=True,
    )

    profile = resolve_demo_run_profile(
        "Pruefe den aktuellen Status von Station S07.", security_context=context
    )
    policy = AgentRunClassificationPolicy().resolve(profile, security_context=context)

    assert profile is AgentRunProfile.RESTRICTED_INFORMATION
    assert policy.data_classification is DataClassification.RESTRICTED
    assert policy.mcp_clearance_ceiling is DataClassification.RESTRICTED
    assert policy.allowed_tool_names == RESTRICTED_INFORMATION_TOOLS
    assert "search_documentation" not in policy.allowed_tool_names
    assert policy.task_requirements.minimum_quality.name == "STANDARD"
    assert policy.task_requirements.cost_preference.name == "MINIMIZE_COST"


def test_restricted_cross_source_product_request_keeps_quality_requirements() -> None:
    context = SecurityContext(
        subject_id="restricted-cross-source",
        roles=("demo-engineer",),
        clearance=DataClassification.RESTRICTED,
        authenticated=True,
    )

    profile = resolve_demo_run_profile(
        "Untersuche Produkt P9001 an Station S07 mit Historie und Dokumentation.",
        security_context=context,
    )
    policy = AgentRunClassificationPolicy().resolve(profile, security_context=context)

    assert profile is AgentRunProfile.RESTRICTED_TROUBLESHOOTING
    assert policy.task_requirements.minimum_quality.name == "HIGH"


@pytest.mark.parametrize(
    ("message", "clearance", "expected"),
    (
        (
            "Liste die mir verfügbaren Produkte auf und fasse ihren Endstatus zusammen.",
            DataClassification.PUBLIC,
            AgentRunProfile.PUBLIC_INFORMATION,
        ),
        (
            "Gib mir einen Überblick über die mir verfügbaren Produkte und ihren Endstatus.",
            DataClassification.INTERNAL,
            AgentRunProfile.INTERNAL_DIAGNOSTIC,
        ),
        (
            "Untersuche Produkt P4801 und fasse seinen sichtbaren Produktionspfad zusammen.",
            DataClassification.CONFIDENTIAL,
            AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        ),
        (
            "Ermittle die kürzlich fehlgeschlagenen Produkte und fasse ihren Fehlerstatus zusammen.",
            DataClassification.CONFIDENTIAL,
            AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        ),
        (
            "Untersuche die Produktionshistorie von P4101.",
            DataClassification.PUBLIC,
            AgentRunProfile.PUBLIC_INFORMATION,
        ),
        (
            "List the products available to me and summarize their final status.",
            DataClassification.PUBLIC,
            AgentRunProfile.PUBLIC_INFORMATION,
        ),
        (
            "Identify recently failed products and summarize their visible failure status.",
            DataClassification.CONFIDENTIAL,
            AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        ),
    ),
)
def test_product_request_resolution_uses_known_entity_or_discovery_scope(
    message: str,
    clearance: DataClassification,
    expected: AgentRunProfile,
) -> None:
    context = SecurityContext(
        subject_id="product-resolution",
        roles=("demo-engineer",),
        clearance=clearance,
        authenticated=True,
    )

    assert resolve_demo_run_profile(message, security_context=context) is expected


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("Untersuche Produkt P4711.", AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING),
        ("Untersuche Produkt P9001.", AgentRunProfile.RESTRICTED_TROUBLESHOOTING),
    ),
)
def test_hidden_product_identifiers_keep_their_authoritative_profile(
    message: str, expected: AgentRunProfile
) -> None:
    assert resolve_demo_run_profile(message) is expected


@pytest.mark.parametrize(
    ("message", "clearance", "allowed", "classification"),
    (
        (
            "Liste verfügbare Produkte.",
            DataClassification.PUBLIC,
            True,
            DataClassification.PUBLIC,
        ),
        (
            "Untersuche P4101.",
            DataClassification.PUBLIC,
            True,
            DataClassification.PUBLIC,
        ),
        (
            "Untersuche P4711.",
            DataClassification.PUBLIC,
            False,
            DataClassification.CONFIDENTIAL,
        ),
        (
            "Untersuche P9001.",
            DataClassification.PUBLIC,
            False,
            DataClassification.RESTRICTED,
        ),
        (
            "Liste verfügbare Produkte.",
            DataClassification.INTERNAL,
            True,
            DataClassification.INTERNAL,
        ),
        (
            "Untersuche P4901.",
            DataClassification.INTERNAL,
            True,
            DataClassification.INTERNAL,
        ),
        (
            "Untersuche P4711.",
            DataClassification.INTERNAL,
            False,
            DataClassification.CONFIDENTIAL,
        ),
        (
            "Untersuche P4801.",
            DataClassification.CONFIDENTIAL,
            True,
            DataClassification.CONFIDENTIAL,
        ),
        (
            "Untersuche P4711.",
            DataClassification.CONFIDENTIAL,
            True,
            DataClassification.CONFIDENTIAL,
        ),
        (
            "Kürzlich fehlgeschlagene Produkte.",
            DataClassification.CONFIDENTIAL,
            True,
            DataClassification.CONFIDENTIAL,
        ),
        (
            "Untersuche P9001.",
            DataClassification.CONFIDENTIAL,
            False,
            DataClassification.RESTRICTED,
        ),
        (
            "Untersuche P4711.",
            DataClassification.RESTRICTED,
            True,
            DataClassification.CONFIDENTIAL,
        ),
        (
            "Untersuche P9001.",
            DataClassification.RESTRICTED,
            True,
            DataClassification.RESTRICTED,
        ),
    ),
)
def test_product_visibility_matrix_keeps_run_classification_at_requested_scope(
    message: str,
    clearance: DataClassification,
    allowed: bool,
    classification: DataClassification,
) -> None:
    context = SecurityContext(
        subject_id="visibility-matrix",
        roles=("demo-engineer",),
        clearance=clearance,
        authenticated=True,
    )
    profile = resolve_demo_run_profile(message, security_context=context)

    if not allowed:
        with pytest.raises(PermissionError, match="unavailable"):
            AgentRunClassificationPolicy().resolve(profile, security_context=context)
        return

    policy = AgentRunClassificationPolicy().resolve(profile, security_context=context)
    assert policy.data_classification is classification
    assert policy.mcp_clearance_ceiling is classification


@pytest.mark.parametrize(
    "clearance",
    (
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
        DataClassification.RESTRICTED,
    ),
)
def test_ticket_lookup_uses_the_confidential_ticket_scope(
    clearance: DataClassification,
) -> None:
    context = SecurityContext(
        subject_id=f"ticket-{clearance.name.lower()}",
        roles=("demo-engineer",),
        clearance=clearance,
        authenticated=True,
    )

    assert (
        resolve_demo_run_profile(
            "Zeige mir das Ticket MT-S02-20260117.", security_context=context
        )
        is AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
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
