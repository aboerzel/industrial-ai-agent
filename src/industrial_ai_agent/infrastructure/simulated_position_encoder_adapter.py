"""Deterministic in-process adapter for the position-encoder recovery scenario."""

from __future__ import annotations

from enum import StrEnum

from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.physical_device import (
    AxisMotionState,
    DeviceCapability,
    DeviceCapabilityName,
    DeviceConnectionState,
    DeviceId,
    DeviceOperation,
    DeviceOperationalState,
    DeviceOperationExecutionStatus,
    DeviceOperationFailureCode,
    DeviceOperationResult,
    DeviceOperationType,
    DeviceState,
)
from industrial_ai_agent.domain.physical_device_port import PhysicalDevicePort
from industrial_ai_agent.domain.product_history import StationId


class SimulatedCalibrationOutcome(StrEnum):
    """Trusted construction-time outcome for the deterministic simulator."""

    SUCCESS = "success"
    VERIFICATION_FAILURE = "verification_failure"
    EXECUTION_FAILURE = "execution_failure"


class SimulatedPositionEncoderAdapter(PhysicalDevicePort):
    """Simulate one bounded position-reference device behind ``PhysicalDevicePort``."""

    device_id = DeviceId("POSITION-ENC-02")
    station_id = StationId("S04")
    tolerance_mm = 0.20

    _reference_position_mm = 12.00
    _initial_position_mm = 12.43
    _calibrated_position_mm = 12.08
    _verification_failure_position_mm = 12.31
    _capabilities = (
        DeviceCapability(DeviceCapabilityName.POSITION_REFERENCE_STATUS),
        DeviceCapability(DeviceCapabilityName.REFERENCE_CALIBRATION),
    )

    def __init__(
        self,
        calibration_outcome: SimulatedCalibrationOutcome = SimulatedCalibrationOutcome.SUCCESS,
        station_mode: MachineState = MachineState.STOPPED,
    ) -> None:
        if not isinstance(calibration_outcome, SimulatedCalibrationOutcome):
            raise TypeError("calibration_outcome must be a SimulatedCalibrationOutcome")
        if not isinstance(station_mode, MachineState):
            raise TypeError("station_mode must be a MachineState")
        self._calibration_outcome = calibration_outcome
        self._station_mode = station_mode
        self._operational_state = DeviceOperationalState.FAULT
        self._reference_valid = False
        self._position_mm = self._initial_position_mm

    def inspect_capabilities(self, device_id: DeviceId) -> tuple[DeviceCapability, ...]:
        self._require_device(device_id)
        return self._capabilities

    def read_state(self, device_id: DeviceId) -> DeviceState:
        self._require_device(device_id)
        return self._snapshot()

    def execute_operation(self, operation: DeviceOperation) -> DeviceOperationResult:
        self._require_device(operation.device_id)
        if operation.operation_type is not DeviceOperationType.REFERENCE_CALIBRATION:
            return DeviceOperationResult(
                operation=operation,
                status=DeviceOperationExecutionStatus.FAILED,
                failure_code=DeviceOperationFailureCode.COMMAND_REJECTED,
            )
        if self._calibration_outcome is SimulatedCalibrationOutcome.EXECUTION_FAILURE:
            return DeviceOperationResult(
                operation=operation,
                status=DeviceOperationExecutionStatus.FAILED,
                failure_code=DeviceOperationFailureCode.DEVICE_REPORTED_FAILURE,
            )

        self._reference_valid = True
        if self._calibration_outcome is SimulatedCalibrationOutcome.SUCCESS:
            self._operational_state = DeviceOperationalState.READY
            self._position_mm = self._calibrated_position_mm
        else:
            self._operational_state = DeviceOperationalState.FAULT
            self._position_mm = self._verification_failure_position_mm
        return DeviceOperationResult(
            operation=operation,
            status=DeviceOperationExecutionStatus.EXECUTED,
        )

    def read_resulting_state(self, device_id: DeviceId) -> DeviceState:
        return self.read_state(device_id)

    def _require_device(self, device_id: DeviceId) -> None:
        if not isinstance(device_id, DeviceId):
            raise TypeError("device_id must be a DeviceId")
        if device_id != self.device_id:
            raise ValueError("Unknown simulated device")

    def _snapshot(self) -> DeviceState:
        return DeviceState(
            device_id=self.device_id,
            station_id=self.station_id,
            connection_state=DeviceConnectionState.CONNECTED,
            operational_state=self._operational_state,
            station_mode=self._station_mode,
            axis_motion_state=AxisMotionState.IDLE,
            product_present=False,
            reference_valid=self._reference_valid,
            position_deviation=abs(self._position_mm - self._reference_position_mm),
        )
