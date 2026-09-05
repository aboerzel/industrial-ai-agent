import pytest
from mcp_types import Tool

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.mcp_access_control import (
    DemoBearerTokenAuthenticator,
    McpAuthenticationError,
    McpAuthorizationError,
    RegisteredMcpClientContextResolver,
    _registration,
)


def _registrations():
    return (
        _registration(
            token="industrial-test-token",
            client_id="industrial-agent",
            clearance=DataClassification.CONFIDENTIAL,
            permissions=frozenset(
                {
                    McpPermission.READ_FACTORY,
                    McpPermission.READ_KNOWLEDGE,
                    McpPermission.CREATE_MAINTENANCE_TICKET,
                }
            ),
        ),
        _registration(
            token="codex-test-token",
            client_id="codex-development",
            clearance=DataClassification.INTERNAL,
            permissions=frozenset(
                {McpPermission.READ_FACTORY, McpPermission.READ_KNOWLEDGE}
            ),
        ),
    )


def test_demo_bearer_authentication_and_access_are_server_owned() -> None:
    registrations = _registrations()
    authenticator = DemoBearerTokenAuthenticator(registrations)
    resolver = RegisteredMcpClientContextResolver(registrations)

    industrial = resolver.resolve(
        authenticator.authenticate("Bearer industrial-test-token")
    )
    codex = resolver.resolve(authenticator.authenticate("Bearer codex-test-token"))

    assert industrial.security_context.clearance == DataClassification.CONFIDENTIAL
    assert industrial.permits(McpPermission.CREATE_MAINTENANCE_TICKET)
    assert codex.security_context.clearance == DataClassification.INTERNAL
    assert not codex.permits(McpPermission.CREATE_MAINTENANCE_TICKET)


@pytest.mark.parametrize(
    "authorization",
    (None, "", "Basic codex-test-token", "Bearer", "Bearer unknown-token"),
)
def test_missing_malformed_and_unknown_bearer_tokens_fail_closed(
    authorization: str | None,
) -> None:
    authenticator = DemoBearerTokenAuthenticator(_registrations())

    with pytest.raises(McpAuthenticationError, match="MCP authentication failed"):
        authenticator.authenticate(authorization)


def test_client_supplied_clearance_and_identity_headers_have_no_authority() -> None:
    from industrial_ai_agent.infrastructure.mcp_access_control import (
        McpHttpAccessControl,
    )

    registrations = _registrations()
    access_control = McpHttpAccessControl(
        authenticator=DemoBearerTokenAuthenticator(registrations),
        resolver=RegisteredMcpClientContextResolver(registrations),
        tools=lambda: _tools(),
        required_permission=lambda name: {
            "get_product_history": McpPermission.READ_FACTORY,
            "create_maintenance_ticket": McpPermission.CREATE_MAINTENANCE_TICKET,
        }[name],
    )
    headers = {
        "authorization": "Bearer codex-test-token",
        "x-client": "industrial-agent",
        "x-clearance": "CONFIDENTIAL",
        "x-permissions": "create_maintenance_ticket",
    }

    context = access_control.access_context_from_headers(headers)

    assert context.identity.client_id == "codex-development"
    assert context.security_context.clearance == DataClassification.INTERNAL
    with pytest.raises(McpAuthorizationError, match="MCP tool is not authorized"):
        access_control.authorize_tool(context, "create_maintenance_ticket")


async def _tools() -> list[Tool]:
    return [
        Tool(name="get_product_history", input_schema={}),
        Tool(name="create_maintenance_ticket", input_schema={}),
    ]
