"""Server-owned classification policy for bounded agent run profiles."""

import re
from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.agent.model_selection import AGENT_CONSUMER, ModelConsumerId
from industrial_ai_agent.domain.maintenance_ticket import is_maintenance_ticket_id
from industrial_ai_agent.domain.security import (
    DataClassification,
    SecurityContext,
    effective_data_classification,
)


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
    "S01": AgentRunProfile.PUBLIC_INFORMATION,
    "S05": AgentRunProfile.PUBLIC_INFORMATION,
}

# Hyphens and Unicode word characters belong to an identifier, not its delimiters.
# Match the whole token before catalogue lookup, including multi-hyphen fault codes.
_EXPLICIT_TARGET_PATTERN = re.compile(
    r"(?<![\w-])(?:P\d{4}|S\d{2,3}|[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)(?![\w-])"
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

# Complete, neutral instruction scaffolds for the bounded demo. Identifiers are
# classified separately; every other character must belong to a supported form.
# Unknown prose is RESTRICTED, regardless of any known target in the same message.
_NEUTRAL_DEMO_REQUEST_FORMS = frozenset(
    {
        "",
        "AND",
        "UND",
        "INVESTIGATE",
        "INVESTIGATE PRODUCT",
        "INVESTIGATE STATION",
        "INVESTIGATE AT",
        "INVESTIGATE PRODUCT AT STATION",
        "INSPECT",
        "INSPECT PRODUCT",
        "SHOW PRODUCT",
        "SHOW TICKET",
        "SHOW ME THE PRODUCTION HISTORY FOR",
        "WHAT IS THE CURRENT STATUS OF STATION",
        "WHY WAS PRODUCT REJECTED",
        "RECOVER THE POSITION REFERENCE AT",
        "UNTERSUCHE",
        "UNTERSUCHE PRODUKT",
        "UNTERSUCHE STATION",
        "UNTERSUCHE AN",
        "UNTERSUCHE PRODUKT AN STATION",
        "UNTERSUCHE DEN ALLGEMEINEN FEHLER AN STATION",
        "UNTERSUCHE DIE PRODUKTIONSHISTORIE VON",
        "UNTERSUCHE PRODUKT UND FASSE SEINEN SICHTBAREN PRODUKTIONSPFAD ZUSAMMEN",
        "UNTERSUCHE PRODUKT AN STATION MIT HISTORIE UND DOKUMENTATION",
        "UNTERSUCHE DEN POSITIONSREFERENZFEHLER AN STATION UND STELLE DIE STATION WIEDER HER",
        "ZEIGE MIR DAS TICKET",
        "ZEIGE DAS WARTUNGSTICKET",
        "ZEIGE DIE VERFÜGBAREN DETAILS ZUM WARTUNGSTICKET",
        "ZEIGE DIE PRODUKTHISTORIE VON",
        "PRUEFE DEN AKTUELLEN STATUS VON STATION",
        "PRÜFE DEN AKTUELLEN STATUS VON STATION",
    }
)
_NEUTRAL_DEMO_DISCOVERY_FORMS = frozenset(
    {
        "WHICH STATIONS ARE AVAILABLE",
        "WHICH PRODUCTS ARE AVAILABLE",
        "LIST THE PRODUCTS AVAILABLE TO ME AND SUMMARIZE THEIR FINAL STATUS",
        "IDENTIFY RECENTLY FAILED PRODUCTS AND SUMMARIZE THEIR VISIBLE FAILURE STATUS",
        "LISTE VERFÜGBARE PRODUKTE",
        "LISTE DIE MIR VERFÜGBAREN PRODUKTE AUF UND FASSE IHREN ENDSTATUS ZUSAMMEN",
        "GIB MIR EINEN ÜBERBLICK ÜBER DIE MIR VERFÜGBAREN PRODUKTE UND IHREN ENDSTATUS",
        "ERMITTLE DIE KÜRZLICH FEHLGESCHLAGENEN PRODUKTE UND FASSE IHREN FEHLERSTATUS ZUSAMMEN",
        "KÜRZLICH FEHLGESCHLAGENE PRODUKTE",
    }
)


def _resolved_identifier_profiles(
    normalized_message: str,
) -> dict[str, AgentRunProfile]:
    """Collect every complete known ID; valid tickets require CONFIDENTIAL scope."""
    profiles = {}
    for match in _EXPLICIT_TARGET_PATTERN.finditer(normalized_message):
        identifier = match.group()
        if identifier in _DEMO_ENTITY_PROFILES:
            profiles[identifier] = _DEMO_ENTITY_PROFILES[identifier]
        elif is_maintenance_ticket_id(identifier):
            profiles[identifier] = AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    return profiles


def _classify_demo_request_content(
    message: str,
    *,
    trusted_context_classification: DataClassification | None,
    security_context: SecurityContext | None,
) -> DataClassification:
    """Fail closed for all text outside supported complete demo request forms."""
    if trusted_context_classification is not None and _is_contextual_follow_up_request(
        message
    ):
        return trusted_context_classification
    normalized = message.strip().upper()
    identifiers = _resolved_identifier_profiles(normalized)
    remainder = _EXPLICIT_TARGET_PATTERN.sub(
        lambda match: " " if match.group() in identifiers else match.group(), normalized
    )
    remainder = " ".join(re.sub(r"[.,;:!?()\[\]{}\"'/]", " ", remainder).split())
    if remainder in _NEUTRAL_DEMO_DISCOVERY_FORMS:
        return (
            security_context.clearance
            if security_context is not None
            else DataClassification.RESTRICTED
        )
    if identifiers and remainder in _NEUTRAL_DEMO_REQUEST_FORMS:
        return DataClassification.PUBLIC
    return DataClassification.RESTRICTED


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
        if not isinstance(self.data_classification, DataClassification):
            raise TypeError("Unknown data classification")
        if not (
            _profile_classification(self.run_profile)
            <= self.mcp_clearance_ceiling
            <= self.data_classification
        ):
            raise ValueError("Run classification must cover its bounded RLS scope")
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
        data_classification: DataClassification | None = None,
    ) -> ResolvedRunPolicy:
        profile_minimum = _profile_classification(profile)
        classification = effective_data_classification(
            profile_minimum,
            data_classification if data_classification is not None else profile_minimum,
        )
        clearance = security_context.clearance if security_context else classification
        if clearance < classification:
            raise RunClearanceDeniedError("Requested demo data is unavailable")
        # Neither higher user clearance nor sensitive request prose broadens the
        # profile's bounded MCP/RLS data view.
        rls_clearance = profile_minimum
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

    def resolve_request(
        self,
        message: str,
        *,
        security_context: SecurityContext | None = None,
        trusted_context_classification: DataClassification | None = None,
    ) -> ResolvedRunPolicy:
        """Resolve domain scope separately from the complete request's sensitivity."""
        profile = resolve_contextual_demo_run_profile(
            message,
            security_context=security_context,
            trusted_context_classification=trusted_context_classification,
        )
        identifier_profiles = _resolved_identifier_profiles(message.strip().upper())
        classification = effective_data_classification(
            _profile_classification(profile),
            *(_profile_classification(item) for item in identifier_profiles.values()),
            _classify_demo_request_content(
                message,
                trusted_context_classification=trusted_context_classification,
                security_context=security_context,
            ),
            (
                trusted_context_classification
                if trusted_context_classification is not None
                else DataClassification.PUBLIC
            ),
        )
        return self.resolve(
            profile,
            security_context=security_context,
            data_classification=classification,
        )

    def resolve_persisted(
        self,
        *,
        profile: AgentRunProfile,
        data_classification: DataClassification,
    ) -> ResolvedRunPolicy:
        if not isinstance(data_classification, DataClassification) or (
            data_classification < _profile_classification(profile)
        ):
            raise ValueError(
                "Persisted run classification is below its profile minimum"
            )
        return self.resolve(profile, data_classification=data_classification)


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
    """Resolve domain behavior for bounded demo targets, never message sensitivity.

    This narrow resolver deliberately recognizes only the documented scenarios. It is
    an outer-demo convenience, not a general data-classification engine.
    """
    normalized = message.strip().upper()
    if _is_s04_position_reference_recovery(normalized):
        return AgentRunProfile.CONFIDENTIAL_RECOVERY
    if _is_restricted_information_request(normalized, security_context):
        return AgentRunProfile.RESTRICTED_INFORMATION
    profiles = _resolved_identifier_profiles(normalized)
    if profiles:
        return max(
            profiles.values(),
            key=lambda item: (_profile_classification(item), item.value),
        )
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
    """Resolve the target profile of a genuine identifierless contextual follow-up.

    The supplied context classification must originate from already-authorized,
    persisted server records. Only a small, explicit set of deictic follow-up forms
    can inherit it. Explicit targets keep their domain behavior; resolve_request owns
    the independent, monotonic classification of the complete request and context.
    """
    resolved = resolve_demo_run_profile(message, security_context=security_context)
    if trusted_context_classification is None:
        return resolved
    normalized = message.strip().upper()
    if _EXPLICIT_TARGET_PATTERN.search(normalized):
        return resolved
    if _is_contextual_follow_up_request(message):
        return _profile_for_classification(trusted_context_classification)
    return resolved


def _is_contextual_follow_up_request(message: str) -> bool:
    return any(
        pattern.fullmatch(message.strip()) for pattern in _CONTEXTUAL_FOLLOW_UP_PATTERNS
    )


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
    identifiers = _resolved_identifier_profiles(normalized_message)
    has_product_identifier = any(
        re.fullmatch(r"P\d{4}", identifier) for identifier in identifiers
    )
    is_station_discovery = (
        "STATION" in normalized_message
        and not has_product_identifier
        and not any(
            marker in normalized_message
            for marker in ("HISTORY", "HISTORIE", "DOCUMENT", "DOKUMENT", "UNTERSUCH")
        )
    )
    is_restricted_station_status = (
        "S07" in identifiers
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


def _is_s04_position_reference_recovery(normalized_message: str) -> bool:
    return "S04" in _resolved_identifier_profiles(normalized_message) and any(
        marker in normalized_message
        for marker in (
            "POSITIONSREFERENZ",
            "POSITION REFERENCE",
            "REFERENCE CALIBRATION",
        )
    )
