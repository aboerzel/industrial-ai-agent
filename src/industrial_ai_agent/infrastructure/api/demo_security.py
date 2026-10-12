"""Server-owned authentication and authorization for the local HTTP demo."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.schemas import DemoUserClearance


class ApiAuthorizationError(Exception):
    """Reject missing, invalid, or insufficient HTTP credentials without details."""


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    token: str
    security_context: SecurityContext


class SecurityContextResolver(Protocol):
    def resolve(
        self,
        authorization: str | None,
        requested_clearance: DemoUserClearance,
    ) -> SecurityContext: ...

    def require_role(
        self, authorization: str | None, role: str
    ) -> SecurityContext: ...


class BearerTokenSecurityContextResolver:
    """Resolve clearance from server-configured bearer tokens, never client claims."""

    def __init__(self, principals: tuple[ApiPrincipal, ...]) -> None:
        normalized_tokens = tuple(principal.token.strip() for principal in principals)
        if any(not token for token in normalized_tokens):
            raise ValueError("API bearer tokens must not be empty")
        if len(set(normalized_tokens)) != len(normalized_tokens):
            raise ValueError("API bearer tokens must be unique")
        self._principals = tuple(
            ApiPrincipal(token, principal.security_context)
            for token, principal in zip(normalized_tokens, principals, strict=True)
        )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str]
    ) -> BearerTokenSecurityContextResolver:
        specifications = (
            (
                "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN",
                DataClassification.PUBLIC,
                ("demo-user",),
            ),
            (
                "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN",
                DataClassification.INTERNAL,
                ("demo-user",),
            ),
            (
                "MCP_INDUSTRIAL_AGENT_TOKEN",
                DataClassification.CONFIDENTIAL,
                ("demo-user", "model-admin"),
            ),
            (
                "MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN",
                DataClassification.RESTRICTED,
                ("demo-user", "model-admin"),
            ),
        )
        principals = tuple(
            ApiPrincipal(
                token=value,
                security_context=SecurityContext(
                    subject_id=f"local-api-{classification.name.lower()}",
                    roles=roles,
                    clearance=classification,
                    authenticated=True,
                ),
            )
            for variable, classification, roles in specifications
            if (value := environment.get(variable, "").strip())
        )
        if not principals:
            raise RuntimeError("At least one API bearer token must be configured")
        return cls(principals)

    def resolve(
        self,
        authorization: str | None,
        requested_clearance: DemoUserClearance,
    ) -> SecurityContext:
        principal = self._principal_for(authorization)
        if principal is None:
            raise ApiAuthorizationError
        requested = DataClassification[requested_clearance.name]
        if requested > principal.security_context.clearance:
            raise ApiAuthorizationError
        return SecurityContext(
            subject_id=principal.security_context.subject_id,
            roles=principal.security_context.roles,
            clearance=requested,
            authenticated=True,
        )

    def require_role(self, authorization: str | None, role: str) -> SecurityContext:
        principal = self._principal_for(authorization)
        if principal is None or role not in principal.security_context.roles:
            raise ApiAuthorizationError
        return principal.security_context

    def _principal_for(self, authorization: str | None) -> ApiPrincipal | None:
        token = _bearer_token(authorization)
        matches = tuple(
            hmac.compare_digest(candidate.token, token)
            for candidate in self._principals
        )
        return next(
            (
                candidate
                for candidate, matches_token in zip(
                    self._principals, matches, strict=True
                )
                if matches_token
            ),
            None,
        )


def _bearer_token(authorization: str | None) -> str:
    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise ApiAuthorizationError
    return token.strip()
