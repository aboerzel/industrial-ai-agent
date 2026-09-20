import inspect

import pytest

from industrial_ai_agent.application.investigation_evidence_adapters import (
    documentation_evidence_from_result,
    machine_state_evidence_from_result,
)
from industrial_ai_agent.domain.investigation_evidence import (
    DocumentationEvidence,
    EvidenceLedger,
    EvidenceRequirementId,
    EvidenceSource,
    EvidenceSourceType,
    InvestigationType,
    MachineStateEvidence,
    required_evidence_for,
)
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.tools.documentation_search import DocumentationSearchResult
from industrial_ai_agent.tools.machine_status import MachineStatusResult

MACHINE_SOURCE = EvidenceSource(EvidenceSourceType.MACHINE_STATE, "tool-call-001")
DOCUMENT_SOURCE = EvidenceSource(EvidenceSourceType.DOCUMENTATION, "tool-call-002")


def test_troubleshooting_uses_the_complete_station_rca_contract() -> None:
    assert required_evidence_for(InvestigationType.STATION_TROUBLESHOOTING) == (
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
        EvidenceRequirementId.ACTIVE_FAULT,
        EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
    )


def test_station_list_and_status_requirements_are_proportional() -> None:
    assert required_evidence_for(InvestigationType.STATION_LIST) == ()
    assert required_evidence_for(InvestigationType.STATION_STATUS) == (
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
    )


def test_trusted_s04_machine_observation_satisfies_state_and_active_fault() -> None:
    ledger = _troubleshooting_ledger().record(_s04_machine_evidence())

    assert tuple(item.requirement for item in ledger.satisfied) == (
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
        EvidenceRequirementId.ACTIVE_FAULT,
    )
    assert ledger.missing == (EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,)


def test_llm_text_cannot_be_recorded_as_evidence() -> None:
    with pytest.raises(TypeError, match="trusted observations only"):
        _troubleshooting_ledger().record("I checked the machine and documentation")  # type: ignore[arg-type]


def test_unrelated_documentation_does_not_satisfy_fault_documentation() -> None:
    ledger = (
        _troubleshooting_ledger()
        .record(_s04_machine_evidence())
        .record(
            DocumentationEvidence(
                fault_id="POSITION-ENC-02",
                document_ids=("doc-position-enc-02",),
                source=DOCUMENT_SOURCE,
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
    )

    assert EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION in ledger.missing


def test_quality_09_documentation_completes_the_trusted_s04_contract() -> None:
    ledger = (
        _troubleshooting_ledger()
        .record(_s04_machine_evidence())
        .record(
            DocumentationEvidence(
                fault_id="QUALITY-09",
                document_ids=("doc-s04quality09procedure",),
                source=DOCUMENT_SOURCE,
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
    )

    assert ledger.complete is True
    assert ledger.missing == ()


def test_documentation_is_not_relevant_until_a_matching_active_fault_is_observed() -> (
    None
):
    ledger = _troubleshooting_ledger().record(
        DocumentationEvidence(
            fault_id="QUALITY-09",
            document_ids=("doc-s04quality09procedure",),
            source=DOCUMENT_SOURCE,
            data_classification=DataClassification.CONFIDENTIAL,
        )
    )

    assert ledger.missing == (
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
        EvidenceRequirementId.ACTIVE_FAULT,
        EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
    )
    assert ledger.record(_s04_machine_evidence()).complete is True


def test_duplicate_observation_is_idempotent() -> None:
    observation = _s04_machine_evidence()
    ledger = _troubleshooting_ledger().record(observation).record(observation)

    assert ledger.observations == (observation,)


def test_same_trusted_observations_produce_the_same_ledger_regardless_of_order() -> (
    None
):
    machine = _s04_machine_evidence()
    documentation = DocumentationEvidence(
        fault_id="QUALITY-09",
        document_ids=("doc-s04quality09procedure",),
        source=DOCUMENT_SOURCE,
        data_classification=DataClassification.CONFIDENTIAL,
    )

    forward = _troubleshooting_ledger().record(machine).record(documentation)
    reverse = _troubleshooting_ledger().record(documentation).record(machine)

    assert forward == reverse
    assert forward.complete is True


def test_restricted_ledger_cannot_be_lowered_by_observation() -> None:
    ledger = EvidenceLedger.for_investigation(
        InvestigationType.STATION_STATUS,
        station_id="S04",
        effective_data_classification=DataClassification.RESTRICTED,
    ).record(
        MachineStateEvidence(
            station_id="S04",
            state=MachineState.FAULTED,
            active_fault_id="QUALITY-09",
            source=MACHINE_SOURCE,
            data_classification=DataClassification.PUBLIC,
        )
    )

    assert ledger.effective_data_classification is DataClassification.RESTRICTED


def test_adapters_map_result_semantics_without_tool_names() -> None:
    machine = machine_state_evidence_from_result(
        MachineStatusResult(
            station_id="S04",
            found=True,
            state=MachineState.FAULTED,
            active_error_code="QUALITY-09",
        ),
        source=MACHINE_SOURCE,
    )
    documentation = documentation_evidence_from_result(
        DocumentationSearchResult(
            query="QUALITY-09",
            results=(
                KnowledgeRetrievalResult(
                    content="Safe projection omitted from the ledger.",
                    document_id="doc-s04quality09procedure",
                    source="S04_Quality_09_Troubleshooting.md",
                    chunk_id="doc-s04quality09procedure::001",
                    metadata={"fault_ids": ("QUALITY-09",)},
                    classification=DataClassification.CONFIDENTIAL,
                ),
            ),
        ),
        fault_id="QUALITY-09",
        source=DOCUMENT_SOURCE,
    )

    assert machine is not None
    assert machine.active_fault_id == "QUALITY-09"
    assert documentation is not None
    assert documentation.document_ids == ("doc-s04quality09procedure",)
    source = inspect.getsource(
        __import__("industrial_ai_agent.domain.investigation_evidence", fromlist=["*"])
    )
    assert "get_machine_status" not in source
    assert "search_documentation" not in source


def test_untrusted_document_content_or_query_cannot_create_documentation_evidence() -> (
    None
):
    result = DocumentationSearchResult(
        query="QUALITY-09",
        results=(
            KnowledgeRetrievalResult(
                content="QUALITY-09 is mentioned, but metadata does not establish relevance.",
                document_id="unrelated-document",
                source="unrelated.md",
                chunk_id="unrelated::001",
            ),
        ),
    )

    assert (
        documentation_evidence_from_result(
            result, fault_id="QUALITY-09", source=DOCUMENT_SOURCE
        )
        is None
    )


def test_physical_recovery_stays_outside_the_investigation_contract() -> None:
    assert required_evidence_for(InvestigationType.PHYSICAL_RECOVERY) == ()


def _troubleshooting_ledger() -> EvidenceLedger:
    return EvidenceLedger.for_investigation(
        InvestigationType.STATION_TROUBLESHOOTING,
        station_id="S04",
        effective_data_classification=DataClassification.CONFIDENTIAL,
    )


def _s04_machine_evidence() -> MachineStateEvidence:
    return MachineStateEvidence(
        station_id="S04",
        state=MachineState.FAULTED,
        active_fault_id="QUALITY-09",
        source=MACHINE_SOURCE,
        data_classification=DataClassification.CONFIDENTIAL,
    )
