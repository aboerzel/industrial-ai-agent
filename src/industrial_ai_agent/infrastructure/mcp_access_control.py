"""HTTP MCP authentication and server-side tool authorization adapters."""

import hmac
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mcp.server.context import CallNext, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_REQUEST, ListToolsResult

from industrial_ai_agent.application.mcp_access import (
    McpAccessContext,
    McpClientContextResolver,
    McpClientIdentity,
    McpPermission,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext

_AUTHORIZATION_HEADER = "authorization"
_AUTHENTICATION_FAILURE_MESSAGE = "MCP authentication failed"
_AUTHORIZATION_FAILURE_MESSAGE = "MCP tool is not authorized"


class McpAuthenticationError(PermissionError):
    """Raised without disclosing credentials or identity matching details."""


class McpAuthorizationError(PermissionError):
    """Raised when a verified client lacks a server-owned MCP permission."""


@dataclass(frozen=True, slots=True)
class DemoMcpClientRegistration:
    """One local-only opaque-token identity mapping assembled at the edge."""

    token: str = field(repr=False)
    identity: McpClientIdentity
    access_context: McpAccessContext

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("MCP demo token must not be empty")
        if self.access_context.identity != self.identity:
            raise ValueError("MCP registration identity must match its access context")


class DemoBearerTokenAuthenticator:
    """Authenticate demo clients from opaque bearer tokens without logging them."""

    def __init__(self, registrations: tuple[DemoMcpClientRegistration, ...]) -> None:
        if not registrations:
            raise ValueError("At least one MCP demo client registration is required")
        identities = {registration.identity.client_id for registration in registrations}
        tokens = {registration.token for registration in registrations}
        if len(identities) != len(registrations) or len(tokens) != len(registrations):
            raise ValueError("MCP demo client registrations must be unique")
        self._registrations = registrations

    def authenticate(self, authorization: str | None) -> McpClientIdentity:
        token = _parse_bearer_token(authorization)
        for registration in self._registrations:
            if hmac.compare_digest(token, registration.token):
                return registration.identity
        raise McpAuthenticationError(_AUTHENTICATION_FAILURE_MESSAGE)


class RegisteredMcpClientContextResolver(McpClientContextResolver):
    """Resolve only pre-registered, authenticated identities to fixed access contexts."""

    def __init__(self, registrations: tuple[DemoMcpClientRegistration, ...]) -> None:
        self._contexts = {
            registration.identity.client_id: registration.access_context
            for registration in registrations
        }

    def resolve(self, identity: McpClientIdentity) -> McpAccessContext:
        try:
            context = self._contexts[identity.client_id]
        except KeyError as error:
            raise McpAuthenticationError(_AUTHENTICATION_FAILURE_MESSAGE) from error
        if context.identity != identity:
            raise McpAuthenticationError(_AUTHENTICATION_FAILURE_MESSAGE)
        return context


class McpHttpAccessControl:
    """Resolve and enforce server-owned access for every HTTP MCP message."""

    def __init__(
        self,
        *,
        authenticator: DemoBearerTokenAuthenticator,
        resolver: McpClientContextResolver,
        tools: Callable[[], Awaitable[list[Any]]],
        required_permission: Callable[[str], McpPermission],
    ) -> None:
        self._authenticator = authenticator
        self._resolver = resolver
        self._tools = tools
        self._required_permission = required_permission

    def access_context_from_headers(
        self, headers: Mapping[str, str] | None
    ) -> McpAccessContext:
        authorization = headers.get(_AUTHORIZATION_HEADER) if headers else None
        identity = self._authenticator.authenticate(authorization)
        return self._resolver.resolve(identity)

    def authorize_tool(self, context: McpAccessContext, tool_name: str) -> None:
        try:
            required = self._required_permission(tool_name)
        except KeyError as error:
            raise McpAuthorizationError(_AUTHORIZATION_FAILURE_MESSAGE) from error
        if not context.permits(required):
            raise McpAuthorizationError(_AUTHORIZATION_FAILURE_MESSAGE)

    async def visible_tools(self, context: McpAccessContext) -> list[Any]:
        return [
            tool
            for tool in await self._tools()
            if context.permits(self._required_permission(tool.name))
        ]

    async def middleware(
        self,
        request: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> object:
        try:
            context = self.access_context_from_headers(_request_headers(request))
            if request.method == "tools/list":
                return ListToolsResult(tools=await self.visible_tools(context))
            if request.method == "tools/call":
                tool_name = _tool_name(request.params)
                self.authorize_tool(context, tool_name)
            return await call_next(request)
        except (McpAuthenticationError, McpAuthorizationError) as error:
            raise MCPError(
                code=INVALID_REQUEST,
                message=str(error),
            ) from error


def create_demo_mcp_access_control(
    *,
    tools: Callable[[], Awaitable[list[Any]]],
    required_permission: Callable[[str], McpPermission],
) -> McpHttpAccessControl:
    """Build the local demo's explicit, server-owned identity policy."""
    industrial_token = _required_environment_value("MCP_INDUSTRIAL_AGENT_TOKEN")
    internal_agent_token = _required_environment_value(
        "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN"
    )
    codex_token = _required_environment_value("MCP_CODEX_DEVELOPMENT_TOKEN")
    registrations = [
        _registration(
            token=industrial_token,
            client_id="industrial-agent",
            clearance=DataClassification.CONFIDENTIAL,
            permissions=frozenset(
                {
                    McpPermission.READ_FACTORY,
                    McpPermission.READ_KNOWLEDGE,
                    McpPermission.READ_OBSERVABILITY,
                    McpPermission.READ_AGENT_RUNTIME,
                    McpPermission.CREATE_MAINTENANCE_TICKET,
                    McpPermission.READ_HARDWARE_STATUS,
                    McpPermission.PREPARE_HARDWARE_RECOVERY,
                }
            ),
        ),
        _registration(
            token=internal_agent_token,
            client_id="industrial-agent-internal",
            clearance=DataClassification.INTERNAL,
            permissions=frozenset(
                {McpPermission.READ_FACTORY, McpPermission.READ_KNOWLEDGE}
            ),
        ),
        _registration(
            token=codex_token,
            client_id="codex-development",
            clearance=DataClassification.INTERNAL,
            permissions=frozenset(
                {
                    McpPermission.READ_FACTORY,
                    McpPermission.READ_KNOWLEDGE,
                    McpPermission.READ_OBSERVABILITY,
                    McpPermission.READ_AGENT_RUNTIME,
                    McpPermission.READ_RCA,
                }
            ),
        ),
    ]
    registrations.extend(
        registration
        for registration in (
            _optional_agent_registration(
                token_name="MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN",
                client_id="industrial-agent-public",
                clearance=DataClassification.PUBLIC,
            ),
            _optional_agent_registration(
                token_name="MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN",
                client_id="industrial-agent-restricted",
                clearance=DataClassification.RESTRICTED,
            ),
        )
        if registration is not None
    )
    return McpHttpAccessControl(
        authenticator=DemoBearerTokenAuthenticator(tuple(registrations)),
        resolver=RegisteredMcpClientContextResolver(tuple(registrations)),
        tools=tools,
        required_permission=required_permission,
    )


def _optional_agent_registration(
    *, token_name: str, client_id: str, clearance: DataClassification
) -> DemoMcpClientRegistration | None:
    token = os.getenv(token_name)
    if token is None or not token.strip():
        return None
    return _registration(
        token=token,
        client_id=client_id,
        clearance=clearance,
        permissions=frozenset(
            {
                McpPermission.READ_FACTORY,
                McpPermission.READ_KNOWLEDGE,
                McpPermission.READ_OBSERVABILITY,
                McpPermission.READ_AGENT_RUNTIME,
                McpPermission.CREATE_MAINTENANCE_TICKET,
                McpPermission.READ_HARDWARE_STATUS,
                McpPermission.PREPARE_HARDWARE_RECOVERY,
            }
        ),
    )


def _registration(
    *,
    token: str,
    client_id: str,
    clearance: DataClassification,
    permissions: frozenset[McpPermission],
) -> DemoMcpClientRegistration:
    identity = McpClientIdentity(client_id=client_id, authenticated=True)
    context = McpAccessContext(
        identity=identity,
        security_context=SecurityContext(
            subject_id=client_id,
            roles=(client_id,),
            clearance=clearance,
            authenticated=True,
        ),
        permissions=permissions,
    )
    return DemoMcpClientRegistration(
        token=token, identity=identity, access_context=context
    )


def _parse_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise McpAuthenticationError(_AUTHENTICATION_FAILURE_MESSAGE)
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token or " " in token:
        raise McpAuthenticationError(_AUTHENTICATION_FAILURE_MESSAGE)
    return token


def _required_environment_value(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be configured")
    return value


def _request_headers(
    request: ServerRequestContext[Any, Any],
) -> Mapping[str, str] | None:
    raw_request = request.request
    return getattr(raw_request, "headers", None)


def _tool_name(params: Mapping[str, Any] | None) -> str:
    name = params.get("name") if params else None
    if not isinstance(name, str) or not name:
        raise McpAuthorizationError(_AUTHORIZATION_FAILURE_MESSAGE)
    return name


def install_mcp_http_access_control(
    server: Any,
    access_control: McpHttpAccessControl,
) -> None:
    """Install public SDK middleware before serving Streamable HTTP."""
    server.middleware.append(access_control.middleware)  # type: ignore[arg-type]
