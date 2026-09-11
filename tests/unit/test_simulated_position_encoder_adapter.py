import pytest

from industrial_ai_agent.domain.closed_loop_recovery import (
    RecoveryOutcome,
    RecoveryResult,
    VerificationCriterion,
    VerificationCriterionType,
    VerificationEvidence,
    VerificationResult,
    VerificationStatus,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.physical_device import (
    ActionRiskClass,
    AxisMotionState,
    DeviceCapabilityName,
    DeviceConnectionState,
    DeviceId,
    DeviceOperation,
    DeviceOperationalState,
    DeviceOperationExecutionStatus,
    DeviceOperationFailureCode,
    DeviceOperationType,
    DeviceState,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.infrastructure.simulated_position_encoder_adapter import (
    SimulatedCalibrationOutcome,
    SimulatedPositionEncoderAdapter,
)


def test_initial_fault_state_exposes_reference_calibration_preconditions() -> None:
    adapter = SimulatedPositionEncoderAdapter()

    state = adapter.read_state(DeviceId("POSITION-ENC-02"))

    assert state.device_id == DeviceId("POSITION-ENC-02")
    assert state.station_id == StationId("S04")
    assert state.connection_state is DeviceConnectionState.CONNECTED
    assert state.operational_state is DeviceOperationalState.FAULT
    assert state.station_mode is MachineState.STOPPED
    assert state.axis_motion_state is AxisMotionState.IDLE
    assert state.product_present is False
    assert state.reference_valid is False
    assert state.position_deviation > adapter.tolerance_mm


def test_capabilities_are_limited_to_reference_status_and_calibration() -> None:
    adapter = SimulatedPositionEncoderAdapter()

    capabilities = adapter.inspect_capabilities(DeviceId("POSITION-ENC-02"))

    assert tuple(capability.name for capability in capabilities) == (
        DeviceCapabilityName.POSITION_REFERENCE_STATUS,
        DeviceCapabilityName.REFERENCE_CALIBRATION,
    )


def test_calibration_executes_and_requires_separate_post_action_verification() -> None:
    adapter = SimulatedPositionEncoderAdapter()
    pre_action_state = adapter.read_state(adapter.device_id)

    operation_result = adapter.execute_operation(_calibration_operation())
    post_action_state = adapter.read_resulting_state(adapter.device_id)
    verification = _reference_verification(post_action_state, adapter.tolerance_mm)

    assert operation_result.status is DeviceOperationExecutionStatus.EXECUTED
    assert operation_result.executed is True
    assert post_action_state.operational_state is DeviceOperationalState.READY
    assert post_action_state.reference_valid is True
    assert post_action_state.position_deviation <= adapter.tolerance_mm
    assert verification.status is VerificationStatus.PASSED
    assert (
        RecoveryResult(
            operation_result=operation_result,
            pre_action_state=pre_action_state,
            post_action_state=post_action_state,
            verification=verification,
            outcome=RecoveryOutcome.SUCCEEDED,
        ).outcome
        is RecoveryOutcome.SUCCEEDED
    )


def test_successful_command_with_failed_verification_cannot_succeed_at_recovery() -> (
    None
):
    adapter = SimulatedPositionEncoderAdapter(
        SimulatedCalibrationOutcome.VERIFICATION_FAILURE
    )
    pre_action_state = adapter.read_state(adapter.device_id)

    operation_result = adapter.execute_operation(_calibration_operation())
    post_action_state = adapter.read_resulting_state(adapter.device_id)
    verification = _reference_verification(post_action_state, adapter.tolerance_mm)

    assert operation_result.executed is True
    assert post_action_state.reference_valid is True
    assert post_action_state.position_deviation > adapter.tolerance_mm
    assert verification.status is VerificationStatus.FAILED
    with pytest.raises(ValueError, match="passed verification"):
        RecoveryResult(
            operation_result=operation_result,
            pre_action_state=pre_action_state,
            post_action_state=post_action_state,
            verification=verification,
            outcome=RecoveryOutcome.SUCCEEDED,
        )


def test_execution_failure_does_not_produce_a_recovered_state() -> None:
    adapter = SimulatedPositionEncoderAdapter(
        SimulatedCalibrationOutcome.EXECUTION_FAILURE
    )
    initial_state = adapter.read_state(adapter.device_id)

    operation_result = adapter.execute_operation(_calibration_operation())
    resulting_state = adapter.read_resulting_state(adapter.device_id)

    assert operation_result.status is DeviceOperationExecutionStatus.FAILED
    assert (
        operation_result.failure_code
        is DeviceOperationFailureCode.DEVICE_REPORTED_FAILURE
    )
    assert operation_result.executed is False
    assert resulting_state == initial_state
    assert resulting_state.operational_state is DeviceOperationalState.FAULT
    assert resulting_state.reference_valid is False


def test_calibration_risk_is_trusted_and_cannot_be_downgraded() -> None:
    operation = _calibration_operation()

    assert operation.risk_class is ActionRiskClass.CONTROLLED_ACTION
    with pytest.raises(TypeError):
        DeviceOperation(
            device_id=operation.device_id,
            operation_type=operation.operation_type,
            risk_class=ActionRiskClass.READ_ONLY,
        )


def test_unknown_operation_is_rejected_without_mutating_device_state() -> None:
    adapter = SimulatedPositionEncoderAdapter()
    initial_state = adapter.read_state(adapter.device_id)

    result = adapter.execute_operation(
        DeviceOperation(
            device_id=adapter.device_id,
            operation_type=DeviceOperationType.READ_STATE,
        )
    )

    assert result.status is DeviceOperationExecutionStatus.FAILED
    assert result.failure_code is DeviceOperationFailureCode.COMMAND_REJECTED
    assert adapter.read_state(adapter.device_id) == initial_state


def _calibration_operation() -> DeviceOperation:
    return DeviceOperation(
        device_id=DeviceId("POSITION-ENC-02"),
        operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
    )


def _reference_verification(
    state: DeviceState, tolerance_mm: float
) -> VerificationResult:
    reference_criterion = VerificationCriterion(
        VerificationCriterionType.REFERENCE_VALID
    )
    deviation_criterion = VerificationCriterion(
        VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE,
        maximum_abs_deviation=tolerance_mm,
    )
    evidence = (
        VerificationEvidence(
            criterion=reference_criterion,
            passed=state.reference_valid is True,
            observed_value=state.reference_valid is True,
        ),
        VerificationEvidence(
            criterion=deviation_criterion,
            passed=state.position_deviation <= tolerance_mm,
            observed_value=state.position_deviation,
        ),
    )
    return VerificationResult(
        status=(
            VerificationStatus.PASSED
            if all(item.passed for item in evidence)
            else VerificationStatus.FAILED
        ),
        evidence=evidence,
    )
