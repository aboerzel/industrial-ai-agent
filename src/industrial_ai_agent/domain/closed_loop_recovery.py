"""Deterministic core contracts for bounded closed-loop recovery."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.physical_device import (
    AxisMotionState,
    DeviceConnectionState,
    DeviceId,
    DeviceOperation,
    DeviceOperationResult,
    DeviceState,
)
from industrial_ai_agent.domain.product_history import StationId


def _bounded_text(value: str, field_name: str, maximum_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized_value = value.strip()
    if not normalized_value or len(normalized_value) > maximum_length:
        raise ValueError(
            f"{field_name} must be between 1 and {maximum_length} characters"
        )
    return normalized_value


class RecoveryPreconditionType(StrEnum):
    STATION_STOPPED = "station_stopped"
    AXIS_IDLE = "axis_idle"
    NO_PRODUCT_PRESENT = "no_product_present"
    DEVICE_CONNECTED = "device_connected"


_PRECONDITION_DESCRIPTIONS = {
    RecoveryPreconditionType.STATION_STOPPED: "Station must be stopped",
    RecoveryPreconditionType.AXIS_IDLE: "Axis motion must be idle",
    RecoveryPreconditionType.NO_PRODUCT_PRESENT: "No product may be present",
    RecoveryPreconditionType.DEVICE_CONNECTED: "Device must be connected",
}


@dataclass(frozen=True, slots=True)
class RecoveryPrecondition:
    condition_type: RecoveryPreconditionType

    def __post_init__(self) -> None:
        if not isinstance(self.condition_type, RecoveryPreconditionType):
            raise TypeError("Unknown recovery precondition")

    @property
    def description(self) -> str:
        return _PRECONDITION_DESCRIPTIONS[self.condition_type]


class PreconditionStatus(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    PASSED = "PASSED"
    FAILED = "FAILED"


PreconditionObservedValue = (
    MachineState | AxisMotionState | DeviceConnectionState | bool | None
)


@dataclass(frozen=True, slots=True)
class PreconditionEvaluation:
    precondition: RecoveryPrecondition
    status: PreconditionStatus
    observed_value: PreconditionObservedValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.precondition, RecoveryPrecondition):
            raise TypeError("precondition must be a RecoveryPrecondition")
        if not isinstance(self.status, PreconditionStatus):
            raise TypeError("Unknown precondition status")
        if self.status is PreconditionStatus.NOT_EVALUATED:
            if self.observed_value is not None:
                raise ValueError(
                    "Unevaluated preconditions must not have an observation"
                )
            return
        expected_value, expected_type = _expected_precondition_value(
            self.precondition.condition_type
        )
        if not isinstance(self.observed_value, expected_type):
            raise TypeError("Observed value does not match the precondition type")
        passed = self.observed_value == expected_value
        if (self.status is PreconditionStatus.PASSED) != passed:
            raise ValueError("Precondition status must match the observed value")


def _expected_precondition_value(
    condition_type: RecoveryPreconditionType,
) -> tuple[MachineState | AxisMotionState | DeviceConnectionState | bool, type[object]]:
    if condition_type is RecoveryPreconditionType.STATION_STOPPED:
        return MachineState.STOPPED, MachineState
    if condition_type is RecoveryPreconditionType.AXIS_IDLE:
        return AxisMotionState.IDLE, AxisMotionState
    if condition_type is RecoveryPreconditionType.NO_PRODUCT_PRESENT:
        return False, bool
    return DeviceConnectionState.CONNECTED, DeviceConnectionState


class VerificationCriterionType(StrEnum):
    REFERENCE_VALID = "reference_valid"
    POSITION_DEVIATION_WITHIN_TOLERANCE = "position_deviation_within_tolerance"
    IMAGE_QUALITY_ACCEPTABLE = "image_quality_acceptable"


@dataclass(frozen=True, slots=True)
class VerificationCriterion:
    criterion_type: VerificationCriterionType
    maximum_abs_deviation: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.criterion_type, VerificationCriterionType):
            raise TypeError("Unknown verification criterion")
        if (
            self.criterion_type
            is VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE
        ):
            if (
                isinstance(self.maximum_abs_deviation, bool)
                or not isinstance(self.maximum_abs_deviation, (int, float))
                or not math.isfinite(self.maximum_abs_deviation)
                or self.maximum_abs_deviation < 0
            ):
                raise ValueError(
                    "Position deviation verification requires a finite non-negative tolerance"
                )
            object.__setattr__(
                self, "maximum_abs_deviation", float(self.maximum_abs_deviation)
            )
        elif self.maximum_abs_deviation is not None:
            raise ValueError("Only deviation verification accepts a tolerance")


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    criteria: tuple[VerificationCriterion, ...]

    def __post_init__(self) -> None:
        normalized_criteria = tuple(self.criteria)
        if not normalized_criteria:
            raise ValueError("Verification plan requires at least one criterion")
        criterion_types = tuple(item.criterion_type for item in normalized_criteria)
        if len(criterion_types) != len(set(criterion_types)):
            raise ValueError("Verification criteria must be unique")
        object.__setattr__(self, "criteria", normalized_criteria)


class VerificationStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    FAILED = "FAILED"


VerificationObservedValue = bool | float


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    criterion: VerificationCriterion
    passed: bool
    observed_value: VerificationObservedValue

    def __post_init__(self) -> None:
        if not isinstance(self.criterion, VerificationCriterion):
            raise TypeError("criterion must be a VerificationCriterion")
        if not isinstance(self.passed, bool):
            raise TypeError("Verification evidence passed must be a bool")
        if (
            self.criterion.criterion_type
            is VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE
        ):
            if (
                isinstance(self.observed_value, bool)
                or not isinstance(self.observed_value, (int, float))
                or not math.isfinite(self.observed_value)
                or self.observed_value < 0
            ):
                raise ValueError(
                    "Deviation evidence must be a finite non-negative number"
                )
            object.__setattr__(self, "observed_value", float(self.observed_value))
            expected_passed = (
                self.observed_value <= self.criterion.maximum_abs_deviation
            )
        elif not isinstance(self.observed_value, bool):
            raise TypeError("Boolean verification criteria require a bool observation")
        else:
            expected_passed = self.observed_value
        if self.passed != expected_passed:
            raise ValueError("Verification evidence passed must match its observation")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    evidence: tuple[VerificationEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, VerificationStatus):
            raise TypeError("Unknown verification status")
        normalized_evidence = tuple(self.evidence)
        criterion_types = tuple(
            item.criterion.criterion_type for item in normalized_evidence
        )
        if len(criterion_types) != len(set(criterion_types)):
            raise ValueError("Verification evidence must have unique criteria")
        if self.status is VerificationStatus.NOT_RUN and normalized_evidence:
            raise ValueError("Unrun verification must not have evidence")
        if self.status is VerificationStatus.PASSED and (
            not normalized_evidence
            or not all(item.passed for item in normalized_evidence)
        ):
            raise ValueError("Passed verification requires passing evidence")
        if self.status is VerificationStatus.FAILED and (
            not normalized_evidence or all(item.passed for item in normalized_evidence)
        ):
            raise ValueError("Failed verification requires failing evidence")
        object.__setattr__(self, "evidence", normalized_evidence)


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    device_id: DeviceId
    station_id: StationId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, DeviceId):
            raise TypeError("device_id must be a DeviceId")
        if self.station_id is not None and not isinstance(self.station_id, StationId):
            raise TypeError("station_id must be a StationId or None")


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    reference: str
    summary: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reference", _bounded_text(self.reference, "reference", 80)
        )
        object.__setattr__(self, "summary", _bounded_text(self.summary, "summary", 500))


@dataclass(frozen=True, slots=True)
class RecoveryProposal:
    target: RecoveryTarget
    problem: str
    evidence: tuple[RecoveryEvidence, ...]
    proposed_action: DeviceOperation
    preconditions: tuple[RecoveryPrecondition, ...]
    requires_approval: bool
    expected_effect: str
    verification_plan: VerificationPlan

    def __post_init__(self) -> None:
        if not isinstance(self.target, RecoveryTarget):
            raise TypeError("target must be a RecoveryTarget")
        if not isinstance(self.proposed_action, DeviceOperation):
            raise TypeError("proposed_action must be a DeviceOperation")
        if not isinstance(self.verification_plan, VerificationPlan):
            raise TypeError("verification_plan must be a VerificationPlan")
        if self.proposed_action.device_id != self.target.device_id:
            raise ValueError("Proposed action must target the recovery device")
        if not isinstance(self.requires_approval, bool):
            raise TypeError("requires_approval must be a bool")
        normalized_evidence = tuple(self.evidence)
        normalized_preconditions = tuple(self.preconditions)
        if any(not isinstance(item, RecoveryEvidence) for item in normalized_evidence):
            raise TypeError("evidence must contain RecoveryEvidence items")
        if any(
            not isinstance(item, RecoveryPrecondition)
            for item in normalized_preconditions
        ):
            raise TypeError("preconditions must contain RecoveryPrecondition items")
        if not normalized_evidence:
            raise ValueError("Recovery proposal requires evidence")
        if not normalized_preconditions:
            raise ValueError("Recovery proposal requires preconditions")
        condition_types = tuple(
            item.condition_type for item in normalized_preconditions
        )
        if len(condition_types) != len(set(condition_types)):
            raise ValueError("Recovery preconditions must be unique")
        object.__setattr__(self, "problem", _bounded_text(self.problem, "problem", 500))
        object.__setattr__(
            self,
            "expected_effect",
            _bounded_text(self.expected_effect, "expected_effect", 500),
        )
        object.__setattr__(self, "evidence", normalized_evidence)
        object.__setattr__(self, "preconditions", normalized_preconditions)


class RecoveryOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    operation_result: DeviceOperationResult | None
    pre_action_state: DeviceState | None
    post_action_state: DeviceState | None
    verification: VerificationResult
    outcome: RecoveryOutcome

    def __post_init__(self) -> None:
        if self.operation_result is not None and not isinstance(
            self.operation_result, DeviceOperationResult
        ):
            raise TypeError("operation_result must be a DeviceOperationResult or None")
        if self.pre_action_state is not None and not isinstance(
            self.pre_action_state, DeviceState
        ):
            raise TypeError("pre_action_state must be a DeviceState or None")
        if self.post_action_state is not None and not isinstance(
            self.post_action_state, DeviceState
        ):
            raise TypeError("post_action_state must be a DeviceState or None")
        if not isinstance(self.verification, VerificationResult):
            raise TypeError("verification must be a VerificationResult")
        if not isinstance(self.outcome, RecoveryOutcome):
            raise TypeError("Unknown recovery outcome")
        if self.outcome is RecoveryOutcome.SUCCEEDED:
            if self.operation_result is None or not self.operation_result.executed:
                raise ValueError("Successful recovery requires an executed operation")
            if self.post_action_state is None:
                raise ValueError("Successful recovery requires post-action observation")
            if self.verification.status is not VerificationStatus.PASSED:
                raise ValueError("Successful recovery requires passed verification")
        if self.outcome is RecoveryOutcome.BLOCKED:
            if self.operation_result is not None:
                raise ValueError("Blocked recovery must not execute an operation")
            if self.verification.status is not VerificationStatus.NOT_RUN:
                raise ValueError("Blocked recovery must not run verification")
        if self.outcome is RecoveryOutcome.FAILED and self.operation_result is None:
            raise ValueError("Failed recovery requires an operation result")

    @property
    def action_executed(self) -> bool:
        return self.operation_result is not None and self.operation_result.executed
