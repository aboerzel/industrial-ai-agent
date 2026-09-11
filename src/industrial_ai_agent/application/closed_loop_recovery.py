"""Deterministic application service for bounded physical-device recovery."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from industrial_ai_agent.domain.closed_loop_recovery import (
    PreconditionEvaluation,
    PreconditionStatus,
    RecoveryOutcome,
    RecoveryPrecondition,
    RecoveryPreconditionType,
    RecoveryProposal,
    RecoveryResult,
    VerificationCriterion,
    VerificationCriterionType,
    VerificationEvidence,
    VerificationResult,
    VerificationStatus,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.physical_device import (
    AxisMotionState,
    DeviceConnectionState,
    DeviceState,
)
from industrial_ai_agent.domain.physical_device_port import PhysicalDevicePort


class RecoveryAuthorizationDecision(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"


class RecoveryAuthorizationPort(Protocol):
    """Authorize a precondition-valid physical recovery before execution."""

    def authorize(
        self,
        proposal: RecoveryProposal,
        precondition_evaluations: tuple[PreconditionEvaluation, ...],
    ) -> RecoveryAuthorizationDecision:
        """Return the trusted authorization decision for one bounded proposal."""


class ClosedLoopRecoveryService:
    """Execute the deterministic observe, authorize, act, observe, verify sequence."""

    def __init__(
        self,
        *,
        physical_devices: PhysicalDevicePort,
        authorization: RecoveryAuthorizationPort,
    ) -> None:
        self._physical_devices = physical_devices
        self._authorization = authorization

    def execute(self, proposal: RecoveryProposal) -> RecoveryResult:
        """Execute one approved bounded proposal without provider or transport dependencies."""
        if not isinstance(proposal, RecoveryProposal):
            raise TypeError("proposal must be a RecoveryProposal")

        pre_action_state = self._physical_devices.read_state(proposal.target.device_id)
        self._validate_observed_target(pre_action_state, proposal)
        precondition_evaluations = tuple(
            self._evaluate_precondition(item, pre_action_state)
            for item in proposal.preconditions
        )
        if not all(
            item.status is PreconditionStatus.PASSED
            for item in precondition_evaluations
        ):
            return RecoveryResult(
                operation_result=None,
                pre_action_state=pre_action_state,
                post_action_state=None,
                verification=VerificationResult(status=VerificationStatus.NOT_RUN),
                outcome=RecoveryOutcome.BLOCKED,
                precondition_evaluations=precondition_evaluations,
            )

        authorization = self._authorization.authorize(
            proposal, precondition_evaluations
        )
        if not isinstance(authorization, RecoveryAuthorizationDecision):
            raise TypeError("authorization must return a RecoveryAuthorizationDecision")
        if authorization is RecoveryAuthorizationDecision.DENIED:
            return RecoveryResult(
                operation_result=None,
                pre_action_state=pre_action_state,
                post_action_state=None,
                verification=VerificationResult(status=VerificationStatus.NOT_RUN),
                outcome=RecoveryOutcome.BLOCKED,
                precondition_evaluations=precondition_evaluations,
            )

        operation_result = self._physical_devices.execute_operation(
            proposal.proposed_action
        )
        if not operation_result.executed:
            return RecoveryResult(
                operation_result=operation_result,
                pre_action_state=pre_action_state,
                post_action_state=None,
                verification=VerificationResult(status=VerificationStatus.NOT_RUN),
                outcome=RecoveryOutcome.FAILED,
                precondition_evaluations=precondition_evaluations,
            )

        post_action_state = self._physical_devices.read_state(proposal.target.device_id)
        self._validate_observed_target(post_action_state, proposal)
        verification = self._evaluate_verification(proposal, post_action_state)
        return RecoveryResult(
            operation_result=operation_result,
            pre_action_state=pre_action_state,
            post_action_state=post_action_state,
            verification=verification,
            outcome=(
                RecoveryOutcome.SUCCEEDED
                if verification.status is VerificationStatus.PASSED
                else RecoveryOutcome.FAILED
            ),
            precondition_evaluations=precondition_evaluations,
        )

    @staticmethod
    def _validate_observed_target(
        state: DeviceState, proposal: RecoveryProposal
    ) -> None:
        if state.device_id != proposal.target.device_id:
            raise ValueError("Observed device does not match the recovery target")
        if (
            proposal.target.station_id is not None
            and state.station_id != proposal.target.station_id
        ):
            raise ValueError("Observed station does not match the recovery target")

    @staticmethod
    def _evaluate_precondition(
        precondition: RecoveryPrecondition, state: DeviceState
    ) -> PreconditionEvaluation:
        observed_value = {
            RecoveryPreconditionType.STATION_STOPPED: state.station_mode,
            RecoveryPreconditionType.AXIS_IDLE: state.axis_motion_state,
            RecoveryPreconditionType.NO_PRODUCT_PRESENT: state.product_present,
            RecoveryPreconditionType.DEVICE_CONNECTED: state.connection_state,
        }[precondition.condition_type]
        if observed_value is None:
            return PreconditionEvaluation(
                precondition=precondition,
                status=PreconditionStatus.NOT_EVALUATED,
            )
        expected_value = {
            RecoveryPreconditionType.STATION_STOPPED: MachineState.STOPPED,
            RecoveryPreconditionType.AXIS_IDLE: AxisMotionState.IDLE,
            RecoveryPreconditionType.NO_PRODUCT_PRESENT: False,
            RecoveryPreconditionType.DEVICE_CONNECTED: DeviceConnectionState.CONNECTED,
        }[precondition.condition_type]
        return PreconditionEvaluation(
            precondition=precondition,
            status=(
                PreconditionStatus.PASSED
                if observed_value == expected_value
                else PreconditionStatus.FAILED
            ),
            observed_value=observed_value,
        )

    @staticmethod
    def _evaluate_verification(
        proposal: RecoveryProposal, state: DeviceState
    ) -> VerificationResult:
        evidence = tuple(
            ClosedLoopRecoveryService._evaluate_criterion(criterion, state)
            for criterion in proposal.verification_plan.criteria
        )
        return VerificationResult(
            status=(
                VerificationStatus.PASSED
                if all(item.passed for item in evidence)
                else VerificationStatus.FAILED
            ),
            evidence=evidence,
        )

    @staticmethod
    def _evaluate_criterion(
        criterion: VerificationCriterion, state: DeviceState
    ) -> VerificationEvidence:
        if criterion.criterion_type is VerificationCriterionType.REFERENCE_VALID:
            observed_value = state.reference_valid is True
            return VerificationEvidence(
                criterion=criterion,
                passed=observed_value,
                observed_value=observed_value,
            )
        if (
            criterion.criterion_type
            is VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE
        ):
            if state.position_deviation is None:
                raise ValueError(
                    "Position-deviation verification requires observed state"
                )
            return VerificationEvidence(
                criterion=criterion,
                passed=state.position_deviation <= criterion.maximum_abs_deviation,
                observed_value=state.position_deviation,
            )
        raise ValueError("Verification criterion is unsupported by PhysicalDevicePort")
