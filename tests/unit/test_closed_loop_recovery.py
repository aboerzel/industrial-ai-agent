import inspect

import pytest

from industrial_ai_agent.domain.closed_loop_recovery import (
    AxisMotionState,
    PreconditionEvaluation,
    PreconditionStatus,
    RecoveryEvidence,
    RecoveryOutcome,
    RecoveryPrecondition,
    RecoveryPreconditionType,
    RecoveryProposal,
    RecoveryResult,
    RecoveryTarget,
    VerificationCriterion,
    VerificationCriterionType,
    VerificationEvidence,
    VerificationPlan,
    VerificationResult,
    VerificationStatus,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.physical_device import (
    ActionRiskClass,
    DeviceConnectionState,
    DeviceId,
    DeviceOperation,
    DeviceOperationExecutionStatus,
    DeviceOperationFailureCode,
    DeviceOperationResult,
    DeviceOperationType,
    DeviceState,
)
from industrial_ai_agent.domain.physical_device_port import PhysicalDevicePort
from industrial_ai_agent.domain.product_history import StationId

DEVICE_ID = DeviceId("POSITION-ENC-02")
STATION_ID = StationId("S04")


def test_controlled_operation_cannot_be_downgraded_by_caller_input() -> None:
    operation = DeviceOperation(
        device_id=DEVICE_ID,
        operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
    )

    assert operation.risk_class is ActionRiskClass.CONTROLLED_ACTION
    with pytest.raises(TypeError):
        DeviceOperation(
            device_id=DEVICE_ID,
            operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
            risk_class=ActionRiskClass.READ_ONLY,
        )


def test_read_only_operation_remains_read_only() -> None:
    operation = DeviceOperation(
        device_id=DEVICE_ID,
        operation_type=DeviceOperationType.READ_STATE,
    )

    assert operation.risk_class is ActionRiskClass.READ_ONLY


def test_recovery_proposal_accepts_the_reference_calibration_contract() -> None:
    proposal = _proposal()

    assert proposal.proposed_action.risk_class is ActionRiskClass.CONTROLLED_ACTION
    assert proposal.requires_approval is True
    assert proposal.preconditions == _preconditions()


def test_recovery_proposal_rejects_an_action_for_another_device() -> None:
    with pytest.raises(ValueError, match="target the recovery device"):
        RecoveryProposal(
            target=RecoveryTarget(device_id=DEVICE_ID, station_id=STATION_ID),
            problem="Reference invalid",
            evidence=(RecoveryEvidence("OBS-001", "Reference is invalid"),),
            proposed_action=DeviceOperation(
                device_id=DeviceId("POSITION-ENC-03"),
                operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
            ),
            preconditions=_preconditions(),
            requires_approval=True,
            expected_effect="Reference becomes valid",
            verification_plan=_verification_plan(),
        )


def test_preconditions_are_closed_and_evaluated_deterministically() -> None:
    precondition = RecoveryPrecondition(RecoveryPreconditionType.STATION_STOPPED)
    passed = PreconditionEvaluation(
        precondition=precondition,
        status=PreconditionStatus.PASSED,
        observed_value=MachineState.STOPPED,
    )

    assert passed.status is PreconditionStatus.PASSED
    with pytest.raises(TypeError, match="Unknown recovery precondition"):
        RecoveryPrecondition("station_stopped")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Observed value"):
        PreconditionEvaluation(
            precondition=precondition,
            status=PreconditionStatus.PASSED,
            observed_value=AxisMotionState.IDLE,
        )
    with pytest.raises(TypeError):
        RecoveryPrecondition(
            RecoveryPreconditionType.STATION_STOPPED,
            expression="station_mode == STOPPED",
        )


def test_successful_recovery_requires_executed_action_and_passed_verification() -> None:
    result = RecoveryResult(
        operation_result=_executed_operation_result(),
        pre_action_state=_state(reference_valid=False, position_deviation=1.2),
        post_action_state=_state(reference_valid=True, position_deviation=0.01),
        verification=_passed_verification(),
        outcome=RecoveryOutcome.SUCCEEDED,
    )

    assert result.action_executed is True
    assert result.outcome is RecoveryOutcome.SUCCEEDED


def test_failed_verification_cannot_report_successful_recovery() -> None:
    with pytest.raises(ValueError, match="passed verification"):
        RecoveryResult(
            operation_result=_executed_operation_result(),
            pre_action_state=_state(reference_valid=False, position_deviation=1.2),
            post_action_state=_state(reference_valid=False, position_deviation=1.2),
            verification=VerificationResult(
                status=VerificationStatus.FAILED,
                evidence=(
                    VerificationEvidence(
                        criterion=VerificationCriterion(
                            VerificationCriterionType.REFERENCE_VALID
                        ),
                        passed=False,
                        observed_value=False,
                    ),
                ),
            ),
            outcome=RecoveryOutcome.SUCCEEDED,
        )


def test_verification_evidence_cannot_claim_a_passing_tolerance_result() -> None:
    with pytest.raises(ValueError, match="must match its observation"):
        VerificationEvidence(
            criterion=VerificationCriterion(
                VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE,
                maximum_abs_deviation=0.05,
            ),
            passed=True,
            observed_value=0.06,
        )


def test_missing_verification_cannot_report_successful_recovery() -> None:
    with pytest.raises(ValueError, match="passed verification"):
        RecoveryResult(
            operation_result=_executed_operation_result(),
            pre_action_state=_state(reference_valid=False, position_deviation=1.2),
            post_action_state=_state(reference_valid=True, position_deviation=0.01),
            verification=VerificationResult(status=VerificationStatus.NOT_RUN),
            outcome=RecoveryOutcome.SUCCEEDED,
        )


def test_blocked_recovery_is_represented_without_an_executed_action() -> None:
    result = RecoveryResult(
        operation_result=None,
        pre_action_state=_state(reference_valid=False, position_deviation=1.2),
        post_action_state=None,
        verification=VerificationResult(status=VerificationStatus.NOT_RUN),
        outcome=RecoveryOutcome.BLOCKED,
    )

    assert result.action_executed is False
    assert result.outcome is RecoveryOutcome.BLOCKED


def test_failed_action_produces_failed_recovery() -> None:
    operation = DeviceOperation(
        device_id=DEVICE_ID,
        operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
    )
    result = RecoveryResult(
        operation_result=DeviceOperationResult(
            operation=operation,
            status=DeviceOperationExecutionStatus.FAILED,
            failure_code=DeviceOperationFailureCode.CONNECTION_UNAVAILABLE,
        ),
        pre_action_state=_state(reference_valid=False, position_deviation=1.2),
        post_action_state=None,
        verification=VerificationResult(status=VerificationStatus.NOT_RUN),
        outcome=RecoveryOutcome.FAILED,
    )

    assert result.action_executed is False
    assert result.outcome is RecoveryOutcome.FAILED


def test_physical_device_port_exposes_only_bounded_domain_operations() -> None:
    assert {
        "inspect_capabilities",
        "read_state",
        "execute_operation",
        "read_resulting_state",
    } == {
        name
        for name, member in PhysicalDevicePort.__dict__.items()
        if not name.startswith("_") and inspect.isfunction(member)
    }


def test_physical_device_core_contracts_do_not_import_outer_technologies() -> None:
    import industrial_ai_agent.domain.closed_loop_recovery as recovery_module
    import industrial_ai_agent.domain.physical_device as device_module
    import industrial_ai_agent.domain.physical_device_port as port_module

    sources = "\n".join(
        inspect.getsource(module)
        for module in (device_module, port_module, recovery_module)
    ).casefold()

    for forbidden_dependency in (
        "industrial_ai_agent.infrastructure",
        "mcp",
        "mhs",
        "opencv",
        "fastapi",
    ):
        assert forbidden_dependency not in sources


def _proposal() -> RecoveryProposal:
    return RecoveryProposal(
        target=RecoveryTarget(device_id=DEVICE_ID, station_id=STATION_ID),
        problem="Position reference is invalid",
        evidence=(
            RecoveryEvidence(
                reference="OBS-001",
                summary="Measured deviation is outside the configured tolerance",
            ),
        ),
        proposed_action=DeviceOperation(
            device_id=DEVICE_ID,
            operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
        ),
        preconditions=_preconditions(),
        requires_approval=True,
        expected_effect="Reference becomes valid within configured tolerance",
        verification_plan=_verification_plan(),
    )


def _preconditions() -> tuple[RecoveryPrecondition, ...]:
    return (
        RecoveryPrecondition(RecoveryPreconditionType.STATION_STOPPED),
        RecoveryPrecondition(RecoveryPreconditionType.AXIS_IDLE),
        RecoveryPrecondition(RecoveryPreconditionType.NO_PRODUCT_PRESENT),
        RecoveryPrecondition(RecoveryPreconditionType.DEVICE_CONNECTED),
    )


def _verification_plan() -> VerificationPlan:
    return VerificationPlan(
        criteria=(
            VerificationCriterion(VerificationCriterionType.REFERENCE_VALID),
            VerificationCriterion(
                VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE,
                maximum_abs_deviation=0.05,
            ),
        )
    )


def _passed_verification() -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.PASSED,
        evidence=(
            VerificationEvidence(
                criterion=VerificationCriterion(
                    VerificationCriterionType.REFERENCE_VALID
                ),
                passed=True,
                observed_value=True,
            ),
            VerificationEvidence(
                criterion=VerificationCriterion(
                    VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE,
                    maximum_abs_deviation=0.05,
                ),
                passed=True,
                observed_value=0.01,
            ),
        ),
    )


def _executed_operation_result() -> DeviceOperationResult:
    return DeviceOperationResult(
        operation=DeviceOperation(
            device_id=DEVICE_ID,
            operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
        ),
        status=DeviceOperationExecutionStatus.EXECUTED,
    )


def _state(
    *,
    reference_valid: bool,
    position_deviation: float,
) -> DeviceState:
    return DeviceState(
        device_id=DEVICE_ID,
        station_id=STATION_ID,
        connection_state=DeviceConnectionState.CONNECTED,
        reference_valid=reference_valid,
        position_deviation=position_deviation,
    )
