"""Complete neutral discovery phrases never classify arbitrary surrounding prose."""

import pytest

from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    RunClearanceDeniedError,
    resolve_demo_discovery_tool,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions


@pytest.mark.parametrize("username", tuple(DemoSessions().users))
def test_exact_reported_prompt_uses_authenticated_discovery_ceiling(username):
    context = DemoSessions().users[username].security_context()
    policy = AgentRunClassificationPolicy().resolve_request(
        "welche stationen kennst du", security_context=context
    )
    assert policy.mcp_clearance_ceiling == context.clearance
    assert policy.data_classification == context.clearance
    assert "list_stations" in policy.allowed_tool_names


@pytest.mark.parametrize(
    "message",
    [
        "customer export is confidential",
        "Welche Stationen kennst du? Details zu S07",
        "Welche Stationen kennst du? SECRET CUSTOMER PRODUCTION PLAN",
        "Which products do you know? confidential customer dimensions",
        "Welche Stationen kennst du? Details zu S08",
        "S07",
        "P9002",
    ],
)
@pytest.mark.parametrize("username", ["demo-public", "demo-confidential", "demo-admin"])
def test_mixed_or_restricted_text_never_inherits_lower_discovery_clearance(
    message, username
):
    context = DemoSessions().users[username].security_context()
    with pytest.raises(RunClearanceDeniedError):
        AgentRunClassificationPolicy().resolve_request(
            message, security_context=context
        )


def test_unknown_text_retains_restricted_classification_for_restricted_user():
    policy = AgentRunClassificationPolicy().resolve_request(
        "synthetic unknown confidential customer plan",
        security_context=DemoSessions().users["demo-restricted"].security_context(),
    )
    assert policy.data_classification is DataClassification.RESTRICTED


@pytest.mark.parametrize(
    "message,tool",
    [
        ("Welche Stationen kennst du?", "list_stations"),
        ("Liste die Stationen auf.", "list_stations"),
        ("Welche Stationen stehen mir zur Verfügung?", "list_stations"),
        ("Welche Produktionsstationen kann ich sehen?", "list_stations"),
        ("Which stations do you know?", "list_stations"),
        ("List the available stations.", "list_stations"),
        ("Which production stations are available to me?", "list_stations"),
        ("Welche Produkte kennst du?", "list_products"),
        ("Liste die verfügbaren Produkte auf.", "list_products"),
        ("Which products do you know?", "list_products"),
        ("List the available products.", "list_products"),
    ],
)
@pytest.mark.parametrize("username", tuple(DemoSessions().users))
def test_complete_allowlisted_inventory_forms_share_the_server_scope(
    message, tool, username
):
    context = DemoSessions().users[username].security_context()
    assert resolve_demo_discovery_tool(message) == tool
    policy = AgentRunClassificationPolicy().resolve_request(
        message, security_context=context
    )
    assert (
        policy.data_classification == policy.mcp_clearance_ceiling == context.clearance
    )
