"""Bounded, provider-independent physical-device contracts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.product_history import StationId

_device_id_pattern = re.compile(r"^[A-Z][A-Z0-9-]{2,63}$")


@dataclass(frozen=True, slots=True)
class DeviceId:
    value: str

    def __post_init__(self) -> None:
        normalized_value = self.value.strip()
        if not _device_id_pattern.fullmatch(normalized_value):
            raise ValueError("Device ID has an invalid format")
        object.__setattr__(self, "value", normalized_value)


class DeviceCapabilityName(StrEnum):
    POSITION_REFERENCE_STATUS = "position_reference_status"
    REFERENCE_CALIBRATION = "reference_calibration"
    CAMERA_STATE = "camera_state"
    IMAGE_CAPTURE = "image_capture"
    CAMERA_EXPOSURE_ADJUSTMENT = "camera_exposure_adjustment"
    CAMERA_GAIN_ADJUSTMENT = "camera_gain_adjustment"
    CAMERA_FOCUS_ADJUSTMENT = "camera_focus_adjustment"


class DeviceCapabilityAccess(StrEnum):
    READ = "read"
    ACTION = "action"


_CAPABILITY_ACCESS = {
    DeviceCapabilityName.POSITION_REFERENCE_STATUS: DeviceCapabilityAccess.READ,
    DeviceCapabilityName.REFERENCE_CALIBRATION: DeviceCapabilityAccess.ACTION,
    DeviceCapabilityName.CAMERA_STATE: DeviceCapabilityAccess.READ,
    DeviceCapabilityName.IMAGE_CAPTURE: DeviceCapabilityAccess.READ,
    DeviceCapabilityName.CAMERA_EXPOSURE_ADJUSTMENT: DeviceCapabilityAccess.ACTION,
    DeviceCapabilityName.CAMERA_GAIN_ADJUSTMENT: DeviceCapabilityAccess.ACTION,
    DeviceCapabilityName.CAMERA_FOCUS_ADJUSTMENT: DeviceCapabilityAccess.ACTION,
}


@dataclass(frozen=True, slots=True)
class DeviceCapability:
    name: DeviceCapabilityName

    def __post_init__(self) -> None:
        if not isinstance(self.name, DeviceCapabilityName):
            raise TypeError("Unknown device capability")

    @property
    def access(self) -> DeviceCapabilityAccess:
        return _CAPABILITY_ACCESS[self.name]


class DeviceConnectionState(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


class DeviceOperationalState(StrEnum):
    FAULT = "FAULT"
    CALIBRATING = "CALIBRATING"
    READY = "READY"


class AxisMotionState(StrEnum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DeviceState:
    device_id: DeviceId
    station_id: StationId | None
    connection_state: DeviceConnectionState
    operational_state: DeviceOperationalState | None = None
    station_mode: MachineState | None = None
    axis_motion_state: AxisMotionState | None = None
    product_present: bool | None = None
    reference_valid: bool | None = None
    position_deviation: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, DeviceId):
            raise TypeError("device_id must be a DeviceId")
        if self.station_id is not None and not isinstance(self.station_id, StationId):
            raise TypeError("station_id must be a StationId or None")
        if not isinstance(self.connection_state, DeviceConnectionState):
            raise TypeError("Unknown device connection state")
        if self.operational_state is not None and not isinstance(
            self.operational_state, DeviceOperationalState
        ):
            raise TypeError("Unknown device operational state")
        if self.station_mode is not None and not isinstance(
            self.station_mode, MachineState
        ):
            raise TypeError("station_mode must be a MachineState or None")
        if self.axis_motion_state is not None and not isinstance(
            self.axis_motion_state, AxisMotionState
        ):
            raise TypeError("Unknown axis motion state")
        if self.product_present is not None and not isinstance(
            self.product_present, bool
        ):
            raise TypeError("product_present must be a bool or None")
        if self.reference_valid is not None and not isinstance(
            self.reference_valid, bool
        ):
            raise TypeError("reference_valid must be a bool or None")
        if self.position_deviation is not None:
            if (
                isinstance(self.position_deviation, bool)
                or not isinstance(self.position_deviation, (int, float))
                or not math.isfinite(self.position_deviation)
                or self.position_deviation < 0
            ):
                raise ValueError(
                    "position_deviation must be a finite non-negative number"
                )
            object.__setattr__(
                self, "position_deviation", float(self.position_deviation)
            )


class ActionRiskClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW_RISK_ACTION = "LOW_RISK_ACTION"
    CONTROLLED_ACTION = "CONTROLLED_ACTION"


class DeviceOperationType(StrEnum):
    READ_STATE = "read_state"
    CAPTURE_IMAGE = "capture_image"
    REFERENCE_CALIBRATION = "reference_calibration"
    ADJUST_CAMERA_EXPOSURE = "adjust_camera_exposure"
    ADJUST_CAMERA_GAIN = "adjust_camera_gain"
    ADJUST_CAMERA_FOCUS = "adjust_camera_focus"


_OPERATION_RISK_CLASS = {
    DeviceOperationType.READ_STATE: ActionRiskClass.READ_ONLY,
    DeviceOperationType.CAPTURE_IMAGE: ActionRiskClass.READ_ONLY,
    DeviceOperationType.REFERENCE_CALIBRATION: ActionRiskClass.CONTROLLED_ACTION,
    DeviceOperationType.ADJUST_CAMERA_EXPOSURE: ActionRiskClass.LOW_RISK_ACTION,
    DeviceOperationType.ADJUST_CAMERA_GAIN: ActionRiskClass.LOW_RISK_ACTION,
    DeviceOperationType.ADJUST_CAMERA_FOCUS: ActionRiskClass.LOW_RISK_ACTION,
}

_SETTING_OPERATIONS = frozenset(
    {
        DeviceOperationType.ADJUST_CAMERA_EXPOSURE,
        DeviceOperationType.ADJUST_CAMERA_GAIN,
        DeviceOperationType.ADJUST_CAMERA_FOCUS,
    }
)


@dataclass(frozen=True, slots=True)
class DeviceOperation:
    device_id: DeviceId
    operation_type: DeviceOperationType
    setting_value: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, DeviceId):
            raise TypeError("device_id must be a DeviceId")
        if not isinstance(self.operation_type, DeviceOperationType):
            raise TypeError("Unknown device operation type")
        if self.operation_type in _SETTING_OPERATIONS:
            if (
                isinstance(self.setting_value, bool)
                or not isinstance(self.setting_value, (int, float))
                or not math.isfinite(self.setting_value)
            ):
                raise ValueError(
                    "Camera adjustment operations require a finite setting_value"
                )
            object.__setattr__(self, "setting_value", float(self.setting_value))
        elif self.setting_value is not None:
            raise ValueError("setting_value is unsupported for this device operation")

    @property
    def risk_class(self) -> ActionRiskClass:
        """Return the trusted, operation-defined risk classification."""
        return _OPERATION_RISK_CLASS[self.operation_type]


class DeviceOperationExecutionStatus(StrEnum):
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class DeviceOperationFailureCode(StrEnum):
    CONNECTION_UNAVAILABLE = "connection_unavailable"
    COMMAND_REJECTED = "command_rejected"
    DEVICE_REPORTED_FAILURE = "device_reported_failure"


@dataclass(frozen=True, slots=True)
class DeviceOperationResult:
    operation: DeviceOperation
    status: DeviceOperationExecutionStatus
    failure_code: DeviceOperationFailureCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, DeviceOperation):
            raise TypeError("operation must be a DeviceOperation")
        if not isinstance(self.status, DeviceOperationExecutionStatus):
            raise TypeError("Unknown device operation execution status")
        if self.status is DeviceOperationExecutionStatus.EXECUTED:
            if self.failure_code is not None:
                raise ValueError("Executed operations must not have a failure code")
        elif not isinstance(self.failure_code, DeviceOperationFailureCode):
            raise ValueError("Failed operations require a bounded failure code")

    @property
    def executed(self) -> bool:
        return self.status is DeviceOperationExecutionStatus.EXECUTED
