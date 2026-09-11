"""Provider- and transport-independent MCP client access model."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from industrial_ai_agent.domain.security import SecurityContext


class McpPermission(StrEnum):
    """Server-authorized capabilities exposed to an MCP client."""

    READ_FACTORY = "read_factory"
    READ_KNOWLEDGE = "read_knowledge"
    READ_OBSERVABILITY = "read_observability"
    READ_AGENT_RUNTIME = "read_agent_runtime"
    READ_RCA = "read_rca"
    CREATE_MAINTENANCE_TICKET = "create_maintenance_ticket"
    READ_HARDWARE_STATUS = "read_hardware_status"
    PREPARE_HARDWARE_RECOVERY = "prepare_hardware_recovery"
    EXECUTE_HARDWARE_RECOVERY = "execute_hardware_recovery"


@dataclass(frozen=True, slots=True)
class McpClientIdentity:
    """Identity established by an outer authentication adapter."""

    client_id: str
    authenticated: bool

    def __post_init__(self) -> None:
        client_id = self.client_id.strip()
        if not client_id:
            raise ValueError("MCP client ID must not be empty")
        if not self.authenticated:
            raise ValueError("MCP client identity must be authenticated")
        object.__setattr__(self, "client_id", client_id)


@dataclass(frozen=True, slots=True)
class McpAccessContext:
    """Server-derived identity, clearance, and permissions for one MCP request."""

    identity: McpClientIdentity
    security_context: SecurityContext
    permissions: frozenset[McpPermission]

    def __post_init__(self) -> None:
        if self.security_context.subject_id != self.identity.client_id:
            raise ValueError(
                "MCP security subject must match the verified client identity"
            )
        if self.security_context.authenticated is not self.identity.authenticated:
            raise ValueError(
                "MCP security context authentication state must match identity"
            )
        if not all(
            isinstance(permission, McpPermission) for permission in self.permissions
        ):
            raise TypeError("Unknown MCP permission")
        object.__setattr__(self, "permissions", frozenset(self.permissions))

    def permits(self, permission: McpPermission) -> bool:
        return permission in self.permissions


class McpClientContextResolver(Protocol):
    """Map an authenticated client identity to server-owned access attributes."""

    def resolve(self, identity: McpClientIdentity) -> McpAccessContext:
        """Return the access context or deny an unknown identity."""
