"""Declarative source semantics for acquiring trusted investigation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.domain.investigation_evidence import EvidenceRequirementId


class EvidenceSourceCapabilityId(StrEnum):
    """Stable identities for source capabilities, independent of concrete tools."""

    MACHINE_STATE_OBSERVATION = "machine_state_observation"
    FAULT_DOCUMENTATION_RETRIEVAL = "fault_documentation_retrieval"


@dataclass(frozen=True, slots=True)
class EvidenceSourceCapability:
    """A source's possible evidence output and evidence prerequisites."""

    capability_id: EvidenceSourceCapabilityId
    can_produce: frozenset[EvidenceRequirementId]
    prerequisites: frozenset[EvidenceRequirementId] = frozenset()

    def __post_init__(self) -> None:
        if not self.can_produce:
            raise ValueError("Evidence source capability must produce evidence")
        if self.can_produce & self.prerequisites:
            raise ValueError("Evidence source cannot require its own output")
