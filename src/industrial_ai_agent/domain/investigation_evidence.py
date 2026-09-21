"""Trusted, tool-independent evidence contracts for industrial investigations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.security import (
    DataClassification,
    effective_data_classification,
)


class InvestigationType(StrEnum):
    """Trusted investigation intents used to select proportional evidence needs."""

    STATION_LIST = "STATION_LIST"
    STATION_STATUS = "STATION_STATUS"
    STATION_TROUBLESHOOTING = "STATION_TROUBLESHOOTING"
    PHYSICAL_RECOVERY = "PHYSICAL_RECOVERY"


class EvidenceRequirementId(StrEnum):
    """Stable domain facts required before a grounded investigation can finish."""

    CURRENT_MACHINE_STATE = "CURRENT_MACHINE_STATE"
    ACTIVE_FAULT = "ACTIVE_FAULT"
    RELEVANT_FAULT_DOCUMENTATION = "RELEVANT_FAULT_DOCUMENTATION"


class EvidenceSourceType(StrEnum):
    """Kinds of trusted observations, deliberately independent of tool names."""

    MACHINE_STATE = "MACHINE_STATE"
    DOCUMENTATION = "DOCUMENTATION"


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    """Safe correlation metadata for one trusted observation."""

    source_type: EvidenceSourceType
    source_reference: str

    def __post_init__(self) -> None:
        normalized = self.source_reference.strip()
        if not normalized:
            raise ValueError("Evidence source reference must not be empty")
        object.__setattr__(self, "source_reference", normalized)


@dataclass(frozen=True, slots=True)
class MachineStateEvidence:
    """A trusted observation of one station's current state."""

    station_id: str
    state: MachineState
    active_fault_id: str | None
    source: EvidenceSource
    data_classification: DataClassification

    def __post_init__(self) -> None:
        station_id = self.station_id.strip().upper()
        if not station_id:
            raise ValueError("Machine-state evidence requires a station ID")
        active_fault_id = (
            self.active_fault_id.strip().upper() if self.active_fault_id else None
        )
        if active_fault_id == "":
            active_fault_id = None
        if not isinstance(self.state, MachineState):
            raise TypeError("Machine-state evidence requires a MachineState")
        if not isinstance(self.data_classification, DataClassification):
            raise TypeError("Unknown machine-state evidence classification")
        object.__setattr__(self, "station_id", station_id)
        object.__setattr__(self, "active_fault_id", active_fault_id)


@dataclass(frozen=True, slots=True)
class DocumentationEvidence:
    """Trusted references proving retrieved documentation applies to a fault."""

    fault_id: str
    document_ids: tuple[str, ...]
    source: EvidenceSource
    data_classification: DataClassification

    def __post_init__(self) -> None:
        fault_id = self.fault_id.strip().upper()
        if not fault_id:
            raise ValueError("Documentation evidence requires a fault ID")
        document_ids = tuple(
            sorted(
                {
                    document_id.strip()
                    for document_id in self.document_ids
                    if document_id.strip()
                }
            )
        )
        if not document_ids:
            raise ValueError("Documentation evidence requires at least one document ID")
        if not isinstance(self.data_classification, DataClassification):
            raise TypeError("Unknown documentation evidence classification")
        object.__setattr__(self, "fault_id", fault_id)
        object.__setattr__(self, "document_ids", document_ids)


TrustedEvidenceObservation = MachineStateEvidence | DocumentationEvidence


@dataclass(frozen=True, slots=True)
class EvidenceSatisfaction:
    """A deterministic requirement-to-trusted-source correlation."""

    requirement: EvidenceRequirementId
    source: EvidenceSource


def required_evidence_for(
    investigation_type: InvestigationType,
) -> tuple[EvidenceRequirementId, ...]:
    """Return the proportional evidence contract for a trusted investigation intent."""
    if not isinstance(investigation_type, InvestigationType):
        raise TypeError("Unknown investigation type")
    return {
        InvestigationType.STATION_LIST: (),
        InvestigationType.STATION_STATUS: (
            EvidenceRequirementId.CURRENT_MACHINE_STATE,
        ),
        InvestigationType.STATION_TROUBLESHOOTING: (
            EvidenceRequirementId.CURRENT_MACHINE_STATE,
            EvidenceRequirementId.ACTIVE_FAULT,
            EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
        ),
        # Recovery has its own precondition, authorization, execution, and verification
        # contract. It deliberately does not reuse investigation-completeness evidence.
        InvestigationType.PHYSICAL_RECOVERY: (),
    }[investigation_type]


@dataclass(frozen=True, slots=True)
class EvidenceLedger:
    """Immutable, classification-preserving ledger over trusted observations only."""

    required: tuple[EvidenceRequirementId, ...]
    station_id: str | None
    effective_data_classification: DataClassification
    observations: tuple[TrustedEvidenceObservation, ...] = ()

    def __post_init__(self) -> None:
        requirements = tuple(self.required)
        if len(requirements) != len(set(requirements)) or any(
            not isinstance(requirement, EvidenceRequirementId)
            for requirement in requirements
        ):
            raise ValueError("Evidence requirements must be unique known identifiers")
        station_id = self.station_id.strip().upper() if self.station_id else None
        if station_id == "":
            station_id = None
        if not isinstance(self.effective_data_classification, DataClassification):
            raise TypeError("Unknown effective evidence classification")
        observations = tuple(self.observations)
        if any(
            not isinstance(item, MachineStateEvidence | DocumentationEvidence)
            for item in observations
        ):
            raise TypeError("Evidence ledger accepts trusted observations only")
        if station_id and any(
            isinstance(item, MachineStateEvidence) and item.station_id != station_id
            for item in observations
        ):
            raise ValueError(
                "Machine-state evidence does not match the investigation station"
            )
        observed_classification = effective_data_classification(
            self.effective_data_classification,
            *(item.data_classification for item in observations),
        )
        object.__setattr__(self, "required", requirements)
        object.__setattr__(self, "station_id", station_id)
        object.__setattr__(
            self, "effective_data_classification", observed_classification
        )
        object.__setattr__(self, "observations", _unique_observations(observations))

    @classmethod
    def for_investigation(
        cls,
        investigation_type: InvestigationType,
        *,
        station_id: str | None,
        effective_data_classification: DataClassification,
    ) -> EvidenceLedger:
        """Create a ledger from trusted intent and run classification."""
        return cls(
            required=required_evidence_for(investigation_type),
            station_id=station_id,
            effective_data_classification=effective_data_classification,
        )

    def record(self, observation: TrustedEvidenceObservation) -> EvidenceLedger:
        """Add one trusted observation idempotently; no model text is accepted here."""
        if not isinstance(observation, MachineStateEvidence | DocumentationEvidence):
            raise TypeError("Evidence ledger accepts trusted observations only")
        return EvidenceLedger(
            required=self.required,
            station_id=self.station_id,
            effective_data_classification=self.effective_data_classification,
            observations=(*self.observations, observation),
        )

    @property
    def satisfied(self) -> tuple[EvidenceSatisfaction, ...]:
        """Return requirement satisfactions in declared requirement order."""
        machine_observations = tuple(
            item for item in self.observations if isinstance(item, MachineStateEvidence)
        )
        documentation_observations = tuple(
            item
            for item in self.observations
            if isinstance(item, DocumentationEvidence)
        )
        active_faults = {
            item.active_fault_id
            for item in machine_observations
            if item.active_fault_id is not None
        }
        healthy_machine_observation = next(
            (
                item
                for item in machine_observations
                if item.state is MachineState.RUNNING and item.active_fault_id is None
            ),
            None,
        )
        satisfactions: list[EvidenceSatisfaction] = []
        for requirement in self.required:
            if (
                requirement is EvidenceRequirementId.CURRENT_MACHINE_STATE
                and machine_observations
            ):
                satisfactions.append(
                    EvidenceSatisfaction(requirement, machine_observations[0].source)
                )
            elif requirement is EvidenceRequirementId.ACTIVE_FAULT and active_faults:
                observation = next(
                    item
                    for item in machine_observations
                    if item.active_fault_id is not None
                )
                satisfactions.append(
                    EvidenceSatisfaction(requirement, observation.source)
                )
            elif (
                requirement is EvidenceRequirementId.ACTIVE_FAULT
                and healthy_machine_observation is not None
            ):
                satisfactions.append(
                    EvidenceSatisfaction(
                        requirement, healthy_machine_observation.source
                    )
                )
            elif requirement is EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION:
                observation = next(
                    (
                        item
                        for item in documentation_observations
                        if item.fault_id in active_faults
                    ),
                    None,
                )
                if observation is not None:
                    satisfactions.append(
                        EvidenceSatisfaction(requirement, observation.source)
                    )
                elif healthy_machine_observation is not None:
                    satisfactions.append(
                        EvidenceSatisfaction(
                            requirement,
                            healthy_machine_observation.source,
                        )
                    )
        return tuple(satisfactions)

    @property
    def missing(self) -> tuple[EvidenceRequirementId, ...]:
        """Return unsatisfied requirements in declared requirement order."""
        satisfied = {item.requirement for item in self.satisfied}
        return tuple(item for item in self.required if item not in satisfied)

    @property
    def complete(self) -> bool:
        """Whether every declared requirement has a trusted satisfaction."""
        return not self.missing


def _unique_observations(
    observations: tuple[TrustedEvidenceObservation, ...],
) -> tuple[TrustedEvidenceObservation, ...]:
    """Normalize trusted observations for idempotent, order-independent ledger state."""
    return tuple(sorted(set(observations), key=_observation_sort_key))


def _observation_sort_key(
    observation: TrustedEvidenceObservation,
) -> tuple[str, str, str, tuple[str, ...], int, str, str]:
    """Order safe correlations only; no machine or document payload enters the ledger."""
    if isinstance(observation, MachineStateEvidence):
        return (
            observation.source.source_type.value,
            observation.source.source_reference,
            observation.station_id,
            (),
            int(observation.data_classification),
            observation.state.value,
            observation.active_fault_id or "",
        )
    return (
        observation.source.source_type.value,
        observation.source.source_reference,
        observation.fault_id,
        observation.document_ids,
        int(observation.data_classification),
        "",
        "",
    )
