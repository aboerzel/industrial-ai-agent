"""Server-configured API identities are independent from working clearance."""

import pytest

from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.demo_security import (
    ApiAuthorizationError,
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.schemas import DemoUserClearance

DEMO_TOKENS = {
    "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "test-public",
    "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN": "test-internal",
    "MCP_INDUSTRIAL_AGENT_TOKEN": "test-confidential",
    "MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN": "test-restricted",
    "AGENT_API_MODEL_ADMIN_TOKEN": "test-admin",
}


@pytest.mark.parametrize("classification", list(DataClassification))
def test_investigation_principals_have_fixed_ceiling_without_model_admin(
    classification: DataClassification,
) -> None:
    resolver = BearerTokenSecurityContextResolver.from_environment(DEMO_TOKENS)
    header = f"Bearer test-{classification.name.lower()}"
    context = resolver.resolve(header, DemoUserClearance[classification.name])
    assert context.subject_id == f"local-api-{classification.name.lower()}"
    assert context.clearance is classification
    assert context.roles == ("demo-user",)
    assert context.authenticated
    assert (
        resolver.resolve(header, DemoUserClearance.PUBLIC).clearance
        is DataClassification.PUBLIC
    )
    with pytest.raises(ApiAuthorizationError):
        resolver.require_role(header, "model-admin")
    for requested in DataClassification:
        if requested > classification:
            with pytest.raises(ApiAuthorizationError):
                resolver.resolve(header, DemoUserClearance[requested.name])


def test_separate_admin_token_does_not_grant_protected_investigation_clearance() -> (
    None
):
    resolver = BearerTokenSecurityContextResolver.from_environment(DEMO_TOKENS)
    context = resolver.require_role("Bearer test-admin", "model-admin")
    assert context.subject_id == "local-api-model-admin"
    assert context.roles == ("model-admin",)
    assert context.clearance is DataClassification.PUBLIC
    with pytest.raises(ApiAuthorizationError):
        resolver.resolve("Bearer test-admin", DemoUserClearance.RESTRICTED)


@pytest.mark.parametrize(
    "authorization", [None, "", "Basic user:password", "Bearer unknown"]
)
def test_invalid_credentials_never_establish_identity(
    authorization: str | None,
) -> None:
    resolver = BearerTokenSecurityContextResolver.from_environment(DEMO_TOKENS)
    with pytest.raises(ApiAuthorizationError):
        resolver.resolve(authorization, DemoUserClearance.PUBLIC)
    with pytest.raises(ApiAuthorizationError):
        resolver.require_role(authorization, "model-admin")


def test_admin_token_must_be_distinct_from_investigation_tokens() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        BearerTokenSecurityContextResolver.from_environment(
            {**DEMO_TOKENS, "AGENT_API_MODEL_ADMIN_TOKEN": "test-restricted"}
        )
