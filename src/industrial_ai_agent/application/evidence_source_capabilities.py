"""Application registration and resolution for evidence-producing tools."""

from __future__ import annotations

from dataclasses import dataclass

from industrial_ai_agent.domain.evidence_source_capability import (
    EvidenceSourceCapability,
    EvidenceSourceCapabilityId,
)
from industrial_ai_agent.domain.investigation_evidence import (
    EvidenceLedger,
    EvidenceRequirementId,
)

MACHINE_STATE_OBSERVATION = EvidenceSourceCapability(
    EvidenceSourceCapabilityId.MACHINE_STATE_OBSERVATION,
    frozenset(
        {
            EvidenceRequirementId.CURRENT_MACHINE_STATE,
            EvidenceRequirementId.ACTIVE_FAULT,
        }
    ),
)
FAULT_DOCUMENTATION_RETRIEVAL = EvidenceSourceCapability(
    EvidenceSourceCapabilityId.FAULT_DOCUMENTATION_RETRIEVAL,
    frozenset(
        {
            EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
        }
    ),
    frozenset(
        {
            EvidenceRequirementId.ACTIVE_FAULT,
        }
    ),
)


@dataclass(frozen=True, slots=True)
class EvidenceToolRegistration:
    """Bind one admitted tool name to a capability at the application boundary."""

    tool_name: str
    source_capability: EvidenceSourceCapability

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("Evidence tool registration requires a tool name")


DEFAULT_EVIDENCE_TOOL_REGISTRATIONS = (
    EvidenceToolRegistration("get_machine_status", MACHINE_STATE_OBSERVATION),
    EvidenceToolRegistration("search_documentation", FAULT_DOCUMENTATION_RETRIEVAL),
)


@dataclass(frozen=True, slots=True)
class EligibleEvidenceTools:
    """Safe resolution result; registration never grants tool admission."""

    source_capabilities: tuple[EvidenceSourceCapabilityId, ...]
    tool_names: tuple[str, ...]


def resolve_eligible_evidence_tools(
    ledger: EvidenceLedger,
    *,
    admitted_tool_names: frozenset[str],
    registrations: tuple[
        EvidenceToolRegistration, ...
    ] = DEFAULT_EVIDENCE_TOOL_REGISTRATIONS,
) -> EligibleEvidenceTools:
    """Intersect relevant, unblocked source capabilities with admitted tools."""
    satisfied = {item.requirement for item in ledger.satisfied}
    missing = set(ledger.missing)
    eligible = tuple(
        registration
        for registration in registrations
        if registration.tool_name in admitted_tool_names
        and registration.source_capability.can_produce & missing
        and registration.source_capability.prerequisites <= satisfied
    )
    return EligibleEvidenceTools(
        source_capabilities=tuple(
            dict.fromkeys(item.source_capability.capability_id for item in eligible)
        ),
        tool_names=tuple(item.tool_name for item in eligible),
    )


def evidence_source_for_tool(
    tool_name: str,
    *,
    registrations: tuple[
        EvidenceToolRegistration, ...
    ] = DEFAULT_EVIDENCE_TOOL_REGISTRATIONS,
) -> EvidenceSourceCapabilityId | None:
    """Return trace-only source metadata for a registered tool."""
    return next(
        (
            registration.source_capability.capability_id
            for registration in registrations
            if registration.tool_name == tool_name
        ),
        None,
    )
