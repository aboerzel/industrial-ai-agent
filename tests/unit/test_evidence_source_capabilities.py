from industrial_ai_agent.application.evidence_source_capabilities import (
    DEFAULT_EVIDENCE_TOOL_REGISTRATIONS,
    MACHINE_STATE_OBSERVATION,
    EvidenceToolRegistration,
    resolve_eligible_evidence_tools,
)
from industrial_ai_agent.domain.investigation_evidence import (
    EvidenceLedger,
    EvidenceSource,
    EvidenceSourceType,
    InvestigationType,
    MachineStateEvidence,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.security import DataClassification


def _ledger(*, active_fault: bool = False) -> EvidenceLedger:
    ledger = EvidenceLedger.for_investigation(
        InvestigationType.STATION_TROUBLESHOOTING,
        station_id="S04",
        effective_data_classification=DataClassification.CONFIDENTIAL,
    )
    if active_fault:
        ledger = ledger.record(
            MachineStateEvidence(
                station_id="S04",
                state=MachineState.FAULTED,
                active_fault_id="QUALITY-09",
                source=EvidenceSource(EvidenceSourceType.MACHINE_STATE, "call-1"),
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
    return ledger


def test_only_machine_state_sources_are_eligible_before_active_fault() -> None:
    eligible = resolve_eligible_evidence_tools(
        _ledger(),
        admitted_tool_names=frozenset(
            {"get_machine_status", "search_documentation", "get_product_history"}
        ),
    )

    assert eligible.tool_names == ("get_machine_status",)
    assert tuple(item.value for item in eligible.source_capabilities) == (
        "machine_state_observation",
    )


def test_fault_documentation_source_becomes_eligible_after_active_fault() -> None:
    eligible = resolve_eligible_evidence_tools(
        _ledger(active_fault=True),
        admitted_tool_names=frozenset({"get_machine_status", "search_documentation"}),
    )

    assert eligible.tool_names == ("search_documentation",)
    assert tuple(item.value for item in eligible.source_capabilities) == (
        "fault_documentation_retrieval",
    )


def test_multiple_admitted_tools_for_one_source_remain_model_choices() -> None:
    registrations = (
        *DEFAULT_EVIDENCE_TOOL_REGISTRATIONS,
        EvidenceToolRegistration(
            "get_backup_machine_status", MACHINE_STATE_OBSERVATION
        ),
    )

    eligible = resolve_eligible_evidence_tools(
        _ledger(),
        admitted_tool_names=frozenset(
            {"get_machine_status", "get_backup_machine_status"}
        ),
        registrations=registrations,
    )

    assert eligible.tool_names == ("get_machine_status", "get_backup_machine_status")


def test_registration_cannot_bypass_tool_admission() -> None:
    eligible = resolve_eligible_evidence_tools(
        _ledger(),
        admitted_tool_names=frozenset({"search_documentation"}),
    )

    assert eligible.tool_names == ()
    assert eligible.source_capabilities == ()


def test_no_source_has_a_deterministic_empty_resolution() -> None:
    eligible = resolve_eligible_evidence_tools(
        _ledger(), admitted_tool_names=frozenset()
    )

    assert eligible.tool_names == ()
