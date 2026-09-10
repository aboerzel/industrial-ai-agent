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
from industrial_ai_agent.domain.maintenance_ticket import is_maintenance_ticket_id
from industrial_ai_agent.domain.security import DataClassification, SecurityContext


class AgentRunProfile(StrEnum):
    """Fixed server-side execution contracts; clients never submit these values."""

    PUBLIC_INFORMATION = "PUBLIC_INFORMATION"
    INTERNAL_DIAGNOSTIC = "INTERNAL_DIAGNOSTIC"
    CONFIDENTIAL_TROUBLESHOOTING = "CONFIDENTIAL_TROUBLESHOOTING"
    RESTRICTED_INFORMATION = "RESTRICTED_INFORMATION"
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
        "get_product_history",
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
RESTRICTED_INFORMATION_TOOLS = frozenset(
    {
        "list_stations",
        "get_station_overview",
        "get_machine_status",
    }
)


# This resolver is deliberately limited to the deterministic FACTORY-DEMO-01
# catalogue. It assigns known identifiers their authoritative seed classification
# before model routing; RLS remains the authoritative enforcement point for data.
_DEMO_ENTITY_PROFILES = {
    "P4101": AgentRunProfile.PUBLIC_INFORMATION,
    "P4102": AgentRunProfile.PUBLIC_INFORMATION,
    "P4900": AgentRunProfile.INTERNAL_DIAGNOSTIC,
    "P4901": AgentRunProfile.INTERNAL_DIAGNOSTIC,
    "P4711": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "P4801": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "P4802": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "P4805": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "P4811": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "P9001": AgentRunProfile.RESTRICTED_TROUBLESHOOTING,
    "S07": AgentRunProfile.RESTRICTED_TROUBLESHOOTING,
    "PROTO-COMM-07": AgentRunProfile.RESTRICTED_TROUBLESHOOTING,
    "S04": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "QUALITY-09": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "POSITION-ENC-02": AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
    "S02": AgentRunProfile.INTERNAL_DIAGNOSTIC,
    "S03": AgentRunProfile.INTERNAL_DIAGNOSTIC,
}


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
        if profile is AgentRunProfile.RESTRICTED_INFORMATION:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                task_requirements=_information_requirements(classification),
                allowed_tool_names=RESTRICTED_INFORMATION_TOOLS,
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


def _information_requirements(classification: DataClassification) -> TaskRequirements:
    """Route bounded read-only orientation through an eligible local fast profile."""
    return TaskRequirements(
        task_role=TaskRole.TROUBLESHOOTING,
        required_capabilities=frozenset(
            {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
        ),
        minimum_quality=QualityClass.STANDARD,
        cost_preference=CostPreference.MINIMIZE_COST,
        data_classification=classification,
    )


def _profile_classification(profile: AgentRunProfile) -> DataClassification:
    return {
        AgentRunProfile.PUBLIC_INFORMATION: DataClassification.PUBLIC,
        AgentRunProfile.INTERNAL_DIAGNOSTIC: DataClassification.INTERNAL,
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING: DataClassification.CONFIDENTIAL,
        AgentRunProfile.RESTRICTED_INFORMATION: DataClassification.RESTRICTED,
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
    if _is_ticket_lookup_request(normalized):
        # The supported ticket creation path is CONFIDENTIAL and the deterministic
        # seeded ticket has the same classification. Treat every syntactically valid
        # ticket lookup as CONFIDENTIAL so hidden and unknown tickets cannot be
        # distinguished by lower-clearance callers before the model boundary.
        return AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    if _is_restricted_information_request(normalized, security_context):
        return AgentRunProfile.RESTRICTED_INFORMATION
    for identifier, profile in _DEMO_ENTITY_PROFILES.items():
        if identifier in normalized:
            return profile
    if security_context is not None and _is_discovery_request(normalized):
        return {
            DataClassification.PUBLIC: AgentRunProfile.PUBLIC_INFORMATION,
            DataClassification.INTERNAL: AgentRunProfile.INTERNAL_DIAGNOSTIC,
            DataClassification.CONFIDENTIAL: AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
            DataClassification.RESTRICTED: AgentRunProfile.RESTRICTED_TROUBLESHOOTING,
        }[security_context.clearance]
    # Unknown sensitivity must not authorize public-cloud model processing.
    return AgentRunProfile.RESTRICTED_TROUBLESHOOTING


def _is_restricted_information_request(
    normalized_message: str,
    security_context: SecurityContext | None,
) -> bool:
    """Recognize bounded station discovery/status requests before model routing."""
    if (
        security_context is None
        or security_context.clearance is not DataClassification.RESTRICTED
    ):
        return False
    has_product_identifier = re.search(r"\bP\d{4}\b", normalized_message) is not None
    is_station_discovery = (
        "STATION" in normalized_message
        and not has_product_identifier
        and not any(
            marker in normalized_message
            for marker in ("HISTORY", "HISTORIE", "DOCUMENT", "DOKUMENT", "UNTERSUCH")
        )
    )
    is_restricted_station_status = (
        "S07" in normalized_message
        and "STATUS" in normalized_message
        and not any(
            marker in normalized_message
            for marker in ("HISTORY", "HISTORIE", "DOCUMENT", "DOKUMENT", "UNTERSUCH")
        )
    )
    return is_station_discovery or is_restricted_station_status


def _is_discovery_request(normalized_message: str) -> bool:
    return any(
        phrase in normalized_message
        for phrase in (
            "STATIONS",
            "STATION",
            "PRODUCTS",
            "PRODUCT",
            "PRODUKTE",
            "PRODUKT",
            "AVAILABLE",
            "VERFÜGBAR",
            "RECENTLY FAILED",
            "KÜRZLICH FEHLGESCHLAGEN",
            "WARNINGS",
            "FAILURES",
            "WARNUNGEN",
            "FEHLER",
        )
    )


def _is_ticket_lookup_request(normalized_message: str) -> bool:
    return any(
        is_maintenance_ticket_id(candidate.strip(".,;:!?()[]{}\"'"))
        for candidate in normalized_message.split()
    )
