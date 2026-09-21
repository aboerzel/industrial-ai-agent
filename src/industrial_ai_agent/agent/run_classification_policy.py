"""Server-owned classification policy for bounded agent run profiles."""

import re
from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.agent.model_selection import AGENT_CONSUMER, ModelConsumerId
from industrial_ai_agent.domain.maintenance_ticket import is_maintenance_ticket_id
from industrial_ai_agent.domain.security import DataClassification, SecurityContext


class AgentRunProfile(StrEnum):
    """Fixed server-side execution contracts; clients never submit these values."""

    PUBLIC_INFORMATION = "PUBLIC_INFORMATION"
    INTERNAL_DIAGNOSTIC = "INTERNAL_DIAGNOSTIC"
    CONFIDENTIAL_TROUBLESHOOTING = "CONFIDENTIAL_TROUBLESHOOTING"
    CONFIDENTIAL_RECOVERY = "CONFIDENTIAL_RECOVERY"
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
        "get_position_reference_status",
        "get_maintenance_ticket",
        "prepare_reference_calibration",
        "search_documentation",
        "execute_reference_calibration",
        "create_maintenance_ticket",
    }
)
CONFIDENTIAL_RECOVERY_TOOLS = frozenset(
    {
        "get_position_reference_status",
        "prepare_reference_calibration",
        "execute_reference_calibration",
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

_EXPLICIT_TARGET_PATTERN = re.compile(
    r"\b(?:P\d{4}|S\d{2,3}|MT-[A-Z0-9-]+|[A-Z][A-Z0-9]*-[A-Z0-9]+)\b"
)
_CONTEXTUAL_FOLLOW_UP_PATTERNS = (
    re.compile(
        r"^(?:what does (?:that|it|the active fault) mean|what is (?:its|the) "
        r"current operating status|why is that relevant|what should i check next)\??$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:was bedeutet (?:das|der aktive fehler)|wie ist (?:sein|der) "
        r"aktueller betriebsstatus|warum ist das relevant|was soll ich als nächstes "
        r"prüfen)\??$",
        re.IGNORECASE,
    ),
)


class RunClearanceDeniedError(PermissionError):
    """The authenticated demo user cannot access the server-resolved run scope."""


@dataclass(frozen=True, slots=True)
class ResolvedRunPolicy:
    """Immutable execution scope resolved solely by deterministic server policy."""

    run_profile: AgentRunProfile
    data_classification: DataClassification
    mcp_clearance_ceiling: DataClassification
    model_consumer_id: ModelConsumerId
    allowed_tool_names: frozenset[str]
    mcp_client_identity: str

    def __post_init__(self) -> None:
        if self.mcp_clearance_ceiling < self.data_classification:
            raise ValueError("RLS clearance cannot be lower than run classification")
        if self.model_consumer_id != AGENT_CONSUMER:
            raise ValueError("Run policy must use the agent model consumer")
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
                model_consumer_id=AGENT_CONSUMER,
                allowed_tool_names=PUBLIC_INFORMATION_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.INTERNAL_DIAGNOSTIC:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                model_consumer_id=AGENT_CONSUMER,
                allowed_tool_names=INTERNAL_DIAGNOSTIC_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                model_consumer_id=AGENT_CONSUMER,
                allowed_tool_names=CONFIDENTIAL_TROUBLESHOOTING_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.CONFIDENTIAL_RECOVERY:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                model_consumer_id=AGENT_CONSUMER,
                allowed_tool_names=CONFIDENTIAL_RECOVERY_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.RESTRICTED_TROUBLESHOOTING:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                model_consumer_id=AGENT_CONSUMER,
                allowed_tool_names=CONFIDENTIAL_TROUBLESHOOTING_TOOLS,
                mcp_client_identity=_mcp_identity_for(rls_clearance),
            )
        if profile is AgentRunProfile.RESTRICTED_INFORMATION:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=classification,
                mcp_clearance_ceiling=rls_clearance,
                model_consumer_id=AGENT_CONSUMER,
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


def _profile_classification(profile: AgentRunProfile) -> DataClassification:
    return {
        AgentRunProfile.PUBLIC_INFORMATION: DataClassification.PUBLIC,
        AgentRunProfile.INTERNAL_DIAGNOSTIC: DataClassification.INTERNAL,
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING: DataClassification.CONFIDENTIAL,
        AgentRunProfile.CONFIDENTIAL_RECOVERY: DataClassification.CONFIDENTIAL,
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
    if _is_s04_position_reference_recovery(normalized):
        return AgentRunProfile.CONFIDENTIAL_RECOVERY
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


def resolve_contextual_demo_run_profile(
    message: str,
    *,
    trusted_context_classification: DataClassification | None,
    security_context: SecurityContext | None = None,
) -> AgentRunProfile:
    """Resolve a bounded contextual follow-up without trusting conversation prose.

    The supplied context classification must originate from already-authorized,
    persisted server records. Only a small, explicit set of deictic follow-up forms
    can inherit it. New explicit targets keep the normal resolver and may only raise
    the resulting classification.
    """
    resolved = resolve_demo_run_profile(message, security_context=security_context)
    if trusted_context_classification is None:
        return resolved
    normalized = message.strip().upper()
    if _EXPLICIT_TARGET_PATTERN.search(normalized):
        return _profile_at_least(resolved, trusted_context_classification)
    if _is_contextual_follow_up_request(message):
        return _profile_for_classification(trusted_context_classification)
    return resolved


def _is_contextual_follow_up_request(message: str) -> bool:
    return any(
        pattern.fullmatch(message.strip()) for pattern in _CONTEXTUAL_FOLLOW_UP_PATTERNS
    )


def _profile_at_least(
    resolved: AgentRunProfile, minimum_classification: DataClassification
) -> AgentRunProfile:
    if _profile_classification(resolved) >= minimum_classification:
        return resolved
    return _profile_for_classification(minimum_classification)


def _profile_for_classification(
    classification: DataClassification,
) -> AgentRunProfile:
    return {
        DataClassification.PUBLIC: AgentRunProfile.PUBLIC_INFORMATION,
        DataClassification.INTERNAL: AgentRunProfile.INTERNAL_DIAGNOSTIC,
        DataClassification.CONFIDENTIAL: AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        DataClassification.RESTRICTED: AgentRunProfile.RESTRICTED_TROUBLESHOOTING,
    }[classification]


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


def _is_s04_position_reference_recovery(normalized_message: str) -> bool:
    return "S04" in normalized_message and any(
        marker in normalized_message
        for marker in (
            "POSITIONSREFERENZ",
            "POSITION REFERENCE",
            "REFERENCE CALIBRATION",
        )
    )
