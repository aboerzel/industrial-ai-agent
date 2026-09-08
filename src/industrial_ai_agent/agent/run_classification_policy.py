"""Server-owned classification policy for bounded agent run profiles."""

import re
from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.agent.model_routing import (
    CostPreference,
    LLMCapability,
    QualityClass,
    TaskRequirements,
    TaskRole,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext


class AgentRunProfile(StrEnum):
    """Fixed server-side execution contracts; clients never submit these values."""

    PUBLIC_INFORMATION = "PUBLIC_INFORMATION"
    INTERNAL_DIAGNOSTIC = "INTERNAL_DIAGNOSTIC"
    CONFIDENTIAL_TROUBLESHOOTING = "CONFIDENTIAL_TROUBLESHOOTING"
    RESTRICTED_TROUBLESHOOTING = "RESTRICTED_TROUBLESHOOTING"


@dataclass(frozen=True, slots=True)
class InternalDiagnosticTarget:
    """Validated bounded resource references for an INTERNAL diagnostic."""

    product_id: str
    station_id: str


INTERNAL_DIAGNOSTIC_TOOLS = frozenset(
    {
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
        "get_maintenance_ticket",
        "search_documentation",
    }
)
PUBLIC_INFORMATION_TOOLS = frozenset(
    {
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_maintenance_ticket",
        "search_documentation",
    }
)
CONFIDENTIAL_TROUBLESHOOTING_TOOLS = frozenset(
    {
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
        "get_maintenance_ticket",
        "search_documentation",
        "create_maintenance_ticket",
    }
)


class RunClearanceDeniedError(PermissionError):
    """The authenticated demo user cannot access the server-resolved run scope."""


@dataclass(frozen=True, slots=True)
class ResolvedRunPolicy:
    """Immutable execution scope resolved solely by deterministic server policy."""

    run_profile: AgentRunProfile
    data_classification: DataClassification
    mcp_clearance_ceiling: DataClassification
    task_requirements: TaskRequirements
    allowed_tool_names: frozenset[str]
    mcp_client_identity: str

    def __post_init__(self) -> None:
        if self.mcp_clearance_ceiling < self.data_classification:
            raise ValueError("RLS clearance cannot be lower than run classification")
        if self.task_requirements.data_classification is not self.data_classification:
            raise ValueError("Task requirements must match the resolved classification")
        if not self.allowed_tool_names:
            raise ValueError("Resolved run policy must authorize at least one tool")
        if not self.mcp_client_identity.strip():
            raise ValueError("Resolved run policy requires an MCP client identity")


class AgentRunClassificationPolicy:
    """Map known server-side profiles to non-downgradable execution scopes."""

    def resolve(
        self,
        profile: AgentRunProfile,
        *,
        security_context: SecurityContext | None = None,
    ) -> ResolvedRunPolicy:
        classification = _profile_classification(profile)
        clearance = security_context.clearance if security_context else classification
        if clearance < classification:
            raise RunClearanceDeniedError("Requested demo data is unavailable")
        # A higher user clearance authorizes the case but cannot broaden a lower-classified
        # run's MCP/RLS data view. The run requirement is the least-privilege ceiling.
        rls_clearance = classification
        if profile is AgentRunProfile.PUBLIC_INFORMATION:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                task_requirements=_requirements(classification),
                allowed_tool_names=PUBLIC_INFORMATION_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.INTERNAL_DIAGNOSTIC:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                task_requirements=_requirements(classification),
                allowed_tool_names=INTERNAL_DIAGNOSTIC_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                task_requirements=_requirements(classification),
                allowed_tool_names=CONFIDENTIAL_TROUBLESHOOTING_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.RESTRICTED_TROUBLESHOOTING:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                task_requirements=_requirements(classification),
                allowed_tool_names=CONFIDENTIAL_TROUBLESHOOTING_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        raise ValueError("Unknown agent run profile")

    def resolve_persisted(
        self,
        *,
        profile: AgentRunProfile,
        data_classification: DataClassification,
    ) -> ResolvedRunPolicy:
        resolved = self.resolve(profile)
        if resolved.data_classification is not data_classification:
            raise ValueError("Persisted run classification does not match its profile")
        return resolved


def _requirements(classification: DataClassification) -> TaskRequirements:
    return TaskRequirements(
        task_role=TaskRole.TROUBLESHOOTING,
        required_capabilities=frozenset(
            {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
        ),
        minimum_quality=QualityClass.HIGH,
        cost_preference=CostPreference.PREFER_QUALITY,
        data_classification=classification,
    )


def _profile_classification(profile: AgentRunProfile) -> DataClassification:
    return {
        AgentRunProfile.PUBLIC_INFORMATION: DataClassification.PUBLIC,
        AgentRunProfile.INTERNAL_DIAGNOSTIC: DataClassification.INTERNAL,
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING: DataClassification.CONFIDENTIAL,
        AgentRunProfile.RESTRICTED_TROUBLESHOOTING: DataClassification.RESTRICTED,
    }[profile]


def _mcp_identity_for(clearance: DataClassification) -> str:
    return {
        DataClassification.PUBLIC: "industrial-agent-public",
        DataClassification.INTERNAL: "industrial-agent-internal",
        DataClassification.CONFIDENTIAL: "industrial-agent",
        DataClassification.RESTRICTED: "industrial-agent-restricted",
    }[clearance]


def resolve_demo_run_profile(
    message: str, *, security_context: SecurityContext | None = None
) -> AgentRunProfile:
    """Classify the bounded synthetic demo cases without accepting a client label.

    This narrow resolver deliberately recognizes only the documented scenarios. It is
    an outer-demo convenience, not a general data-classification engine.
    """
    normalized = message.strip().upper()
    if any(
        identifier in normalized for identifier in ("P9001", "S07", "PROTO-COMM-07")
    ):
        return AgentRunProfile.RESTRICTED_TROUBLESHOOTING
    if any(
        identifier in normalized
        for identifier in ("P4711", "S04", "QUALITY-09", "POSITION-ENC-02")
    ):
        return AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    if "P4900" in normalized or "P4901" in normalized or "S02" in normalized:
        return AgentRunProfile.INTERNAL_DIAGNOSTIC
    if security_context is not None and (
        _is_discovery_request(normalized) or _is_ticket_lookup_request(normalized)
    ):
        return {
            DataClassification.PUBLIC: AgentRunProfile.PUBLIC_INFORMATION,
            DataClassification.INTERNAL: AgentRunProfile.INTERNAL_DIAGNOSTIC,
            DataClassification.CONFIDENTIAL: AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
            DataClassification.RESTRICTED: AgentRunProfile.RESTRICTED_TROUBLESHOOTING,
        }[security_context.clearance]
    # Unknown sensitivity must not authorize public-cloud model processing.
    return AgentRunProfile.RESTRICTED_TROUBLESHOOTING


def _is_discovery_request(normalized_message: str) -> bool:
    return any(
        phrase in normalized_message
        for phrase in (
            "STATIONS",
            "STATION",
            "PRODUCTS",
            "PRODUCT",
            "AVAILABLE",
            "RECENTLY FAILED",
            "WARNINGS",
            "FAILURES",
        )
    )


def _is_ticket_lookup_request(normalized_message: str) -> bool:
    return bool(re.search(r"\bMT-[A-F0-9]{12}\b", normalized_message))
