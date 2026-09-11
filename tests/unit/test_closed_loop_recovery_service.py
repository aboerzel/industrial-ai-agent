import inspect

import pytest

from industrial_ai_agent.application.closed_loop_recovery import (
    ClosedLoopRecoveryService,
    RecoveryAuthorizationDecision,
)
from industrial_ai_agent.domain.closed_loop_recovery import (
    PreconditionEvaluation,
    PreconditionStatus,
    RecoveryEvidence,
    RecoveryOutcome,
    RecoveryPrecondition,
    RecoveryPreconditionType,
    RecoveryProposal,
    RecoveryTarget,
    VerificationCriterion,
    VerificationCriterionType,
    VerificationPlan,
    VerificationStatus,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.physical_device import (
    DeviceId,
    DeviceOperation,
    DeviceOperationType,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.infrastructure.simulated_position_encoder_adapter import (
    SimulatedCalibrationOutcome,
    SimulatedPositionEncoderAdapter,
)

DEVICE_ID = DeviceId("POSITION-ENC-02")
STATION_ID = StationId("S04")


class RecordingAuthorization:
    def __init__(
        self, decision: RecoveryAuthorizationDecision, calls: list[str]
    ) -> None:
        self._decision = decision
        self._calls = calls
        self.calls = 0
        self.precondition_evaluations: tuple[PreconditionEvaluation, ...] = ()

    def authorize(
        self,
        proposal: RecoveryProposal,
        precondition_evaluations: tuple[PreconditionEvaluation, ...],
    ) -> RecoveryAuthorizationDecision:
        self.calls += 1
        self.precondition_evaluations = precondition_evaluations
        self._calls.append("authorize")
        return self._decision


class RecordingPhysicalDevicePort:
    def __init__(
        self,
        delegate: SimulatedPositionEncoderAdapter,
        calls: list[str],
        *,
        return_mismatched_state: bool = False,
    ) -> None:
        self._delegate = delegate
        self._calls = calls
        self._return_mismatched_state = return_mismatched_state
        self.execute_calls = 0

    def inspect_capabilities(self, device_id: DeviceId):  # type: ignore[no-untyped-def]
        return self._delegate.inspect_capabilities(device_id)

    def read_state(self, device_id: DeviceId):  # type: ignore[no-untyped-def]
        self._calls.append("read_state")
        if self._return_mismatched_state:
            return self._delegate.read_state(self._delegate.device_id)
        return self._delegate.read_state(device_id)

    def execute_operation(self, operation: DeviceOperation):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        self._calls.append("execute_operation")
        return self._delegate.execute_operation(operation)

    def read_resulting_state(self, device_id: DeviceId):  # type: ignore[no-untyped-def]
        return self._delegate.read_resulting_state(device_id)


def test_successful_recovery_reads_fresh_post_action_state_in_order() -> None:
    calls: list[str] = []
    devices = RecordingPhysicalDevicePort(SimulatedPositionEncoderAdapter(), calls)
    authorization = RecordingAuthorization(
        RecoveryAuthorizationDecision.AUTHORIZED, calls
    )

    result = ClosedLoopRecoveryService(
        physical_devices=devices, authorization=authorization
    ).execute(_proposal())

    assert calls == ["read_state", "authorize", "execute_operation", "read_state"]
    assert result.outcome is RecoveryOutcome.SUCCEEDED
    assert result.action_executed is True
    assert result.post_action_state is not result.pre_action_state
    assert result.verification.status is VerificationStatus.PASSED
    assert all(
        item.status is PreconditionStatus.PASSED
        for item in authorization.precondition_evaluations
    )
    assert all(
        item.status is PreconditionStatus.PASSED
        for item in result.precondition_evaluations
    )


def test_successful_operation_with_failed_fresh_verification_fails_recovery() -> None:
    result = _service(
        SimulatedPositionEncoderAdapter(
            SimulatedCalibrationOutcome.VERIFICATION_FAILURE
        )
    ).execute(_proposal())

    assert result.action_executed is True
    assert result.verification.status is VerificationStatus.FAILED
    assert result.outcome is RecoveryOutcome.FAILED


def test_execution_failure_stops_without_post_action_read() -> None:
    calls: list[str] = []
    devices = RecordingPhysicalDevicePort(
        SimulatedPositionEncoderAdapter(SimulatedCalibrationOutcome.EXECUTION_FAILURE),
        calls,
    )
    authorization = RecordingAuthorization(
        RecoveryAuthorizationDecision.AUTHORIZED, calls
    )

    result = ClosedLoopRecoveryService(
        physical_devices=devices, authorization=authorization
    ).execute(_proposal())

    assert calls == ["read_state", "authorize", "execute_operation"]
    assert result.action_executed is False
    assert result.post_action_state is None
    assert result.verification.status is VerificationStatus.NOT_RUN
    assert result.outcome is RecoveryOutcome.FAILED


def test_failed_precondition_blocks_before_authorization_and_execution() -> None:
    calls: list[str] = []
    devices = RecordingPhysicalDevicePort(
        SimulatedPositionEncoderAdapter(station_mode=MachineState.RUNNING), calls
    )
    authorization = RecordingAuthorization(
        RecoveryAuthorizationDecision.AUTHORIZED, calls
    )

    result = ClosedLoopRecoveryService(
        physical_devices=devices, authorization=authorization
    ).execute(_proposal())

    assert calls == ["read_state"]
    assert devices.execute_calls == 0
    assert authorization.calls == 0
    assert result.outcome is RecoveryOutcome.BLOCKED
    assert result.verification.status is VerificationStatus.NOT_RUN
    assert result.precondition_evaluations[0].status is PreconditionStatus.FAILED


def test_denied_authorization_blocks_before_execution() -> None:
    calls: list[str] = []
    devices = RecordingPhysicalDevicePort(SimulatedPositionEncoderAdapter(), calls)
    authorization = RecordingAuthorization(RecoveryAuthorizationDecision.DENIED, calls)

    result = ClosedLoopRecoveryService(
        physical_devices=devices, authorization=authorization
    ).execute(_proposal())

    assert calls == ["read_state", "authorize"]
    assert devices.execute_calls == 0
    assert result.outcome is RecoveryOutcome.BLOCKED
    assert result.verification.status is VerificationStatus.NOT_RUN


def test_mismatched_observed_device_blocks_execution() -> None:
    calls: list[str] = []
    devices = RecordingPhysicalDevicePort(
        SimulatedPositionEncoderAdapter(), calls, return_mismatched_state=True
    )
    authorization = RecordingAuthorization(
        RecoveryAuthorizationDecision.AUTHORIZED, calls
    )

    with pytest.raises(ValueError, match="Observed device"):
        ClosedLoopRecoveryService(
            physical_devices=devices, authorization=authorization
        ).execute(_proposal(target_device_id=DeviceId("POSITION-ENC-03")))

    assert calls == ["read_state"]
    assert devices.execute_calls == 0
    assert authorization.calls == 0


def test_application_service_does_not_depend_on_outer_technologies_or_simulator() -> (
    None
):
    import industrial_ai_agent.application.closed_loop_recovery as service_module

    source = inspect.getsource(service_module).casefold()

    for forbidden_dependency in (
        "industrial_ai_agent.infrastructure",
        "langgraph",
        "langchain",
        "llm",
        "mcp",
        "mhs",
        "opencv",
        "fastapi",
    ):
        assert forbidden_dependency not in source


def _service(adapter: SimulatedPositionEncoderAdapter) -> ClosedLoopRecoveryService:
    return ClosedLoopRecoveryService(
        physical_devices=adapter,
        authorization=RecordingAuthorization(
            RecoveryAuthorizationDecision.AUTHORIZED, []
        ),
    )


def _proposal(target_device_id: DeviceId = DEVICE_ID) -> RecoveryProposal:
    return RecoveryProposal(
        target=RecoveryTarget(device_id=target_device_id, station_id=STATION_ID),
        problem="Position reference is invalid",
        evidence=(
            RecoveryEvidence(
                reference="OBS-001",
                summary="Measured deviation is outside the configured tolerance",
            ),
        ),
        proposed_action=DeviceOperation(
            device_id=target_device_id,
            operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
        ),
        preconditions=(
            RecoveryPrecondition(RecoveryPreconditionType.STATION_STOPPED),
            RecoveryPrecondition(RecoveryPreconditionType.AXIS_IDLE),
            RecoveryPrecondition(RecoveryPreconditionType.NO_PRODUCT_PRESENT),
            RecoveryPrecondition(RecoveryPreconditionType.DEVICE_CONNECTED),
        ),
        requires_approval=True,
        expected_effect="Reference becomes valid within configured tolerance",
        verification_plan=VerificationPlan(
            criteria=(
                VerificationCriterion(VerificationCriterionType.REFERENCE_VALID),
                VerificationCriterion(
                    VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE,
                    maximum_abs_deviation=0.20,
                ),
            )
        ),
    )
