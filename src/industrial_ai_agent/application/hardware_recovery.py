"""Read-only and preparation use cases for bounded physical-device recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from industrial_ai_agent.application.closed_loop_recovery import (
    ClosedLoopRecoveryService,
    RecoveryAuthorizationDecision,
    RecoveryAuthorizationPort,
    evaluate_recovery_preconditions,
)
from industrial_ai_agent.domain.closed_loop_recovery import (
    PreconditionEvaluation,
    RecoveryEvidence,
    RecoveryPrecondition,
    RecoveryPreconditionType,
    RecoveryProposal,
    RecoveryResult,
    RecoveryTarget,
    VerificationCriterion,
    VerificationCriterionType,
    VerificationPlan,
)
from industrial_ai_agent.domain.physical_device import (
    DeviceCapability,
    DeviceCapabilityName,
    DeviceId,
    DeviceOperation,
    DeviceOperationType,
    DeviceState,
)
from industrial_ai_agent.domain.physical_device_port import PhysicalDevicePort
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification, SecurityContext

REFERENCE_CALIBRATION_CLASSIFICATION = DataClassification.CONFIDENTIAL
REFERENCE_CALIBRATION_TOLERANCE_MM = 0.20


class HardwareRecoveryNotAccessibleError(LookupError):
    """Raised without distinguishing absent, inaccessible, or mismatched targets."""


class PositionReferenceDeviceResolver(Protocol):
    """Resolve the one bounded position-reference target for an authorized station."""

    def resolve_position_reference_device(
        self, station_id: StationId
    ) -> DeviceId | None:
        """Return the configured device or ``None`` without enumerating devices."""


@dataclass(frozen=True, slots=True)
class PositionReferenceStatus:
    state: DeviceState
    calibration_supported: bool
    classification: DataClassification


@dataclass(frozen=True, slots=True)
class ReferenceCalibrationPreparation:
    proposal: RecoveryProposal
    precondition_evaluations: tuple[PreconditionEvaluation, ...]
    classification: DataClassification


class TrustedRecoveryApprovalClaimPort(Protocol):
    """Consume one approved, run-bound reference-calibration action."""

    async def claim_reference_calibration(
        self,
        *,
        run_id: UUID,
        action_id: str,
        station_id: StationId,
        device_id: DeviceId,
    ) -> bool:
        """Return whether the exact trusted approval was claimed once."""


@dataclass(frozen=True, slots=True)
class TrustedReferenceCalibrationAuthorization(RecoveryAuthorizationPort):
    """Authorize only a server-validated approved reference-calibration proposal."""

    security_context: SecurityContext
    classification: DataClassification
    target: RecoveryTarget
    approved: bool
    mcp_execution_permitted: bool

    def authorize(
        self,
        proposal: RecoveryProposal,
        precondition_evaluations: tuple[PreconditionEvaluation, ...],
    ) -> RecoveryAuthorizationDecision:
        del precondition_evaluations
        if (
            not self.approved
            or not self.mcp_execution_permitted
            or self.security_context.clearance < self.classification
            or proposal.target != self.target
            or proposal.proposed_action.operation_type
            is not DeviceOperationType.REFERENCE_CALIBRATION
        ):
            return RecoveryAuthorizationDecision.DENIED
        return RecoveryAuthorizationDecision.AUTHORIZED


class HardwareRecoveryPreparationService:
    """Build trusted status and controlled-action preparation from a device port."""

    def __init__(
        self,
        *,
        physical_devices: PhysicalDevicePort,
        classification: DataClassification = REFERENCE_CALIBRATION_CLASSIFICATION,
        tolerance_mm: float = REFERENCE_CALIBRATION_TOLERANCE_MM,
    ) -> None:
        if not isinstance(classification, DataClassification):
            raise TypeError("classification must be a DataClassification")
        if isinstance(tolerance_mm, bool) or not isinstance(tolerance_mm, (int, float)):
            raise TypeError("tolerance_mm must be a number")
        criterion = VerificationCriterion(
            VerificationCriterionType.POSITION_DEVIATION_WITHIN_TOLERANCE,
            maximum_abs_deviation=tolerance_mm,
        )
        self._physical_devices = physical_devices
        self._classification = classification
        self._verification_plan = VerificationPlan(
            criteria=(
                VerificationCriterion(VerificationCriterionType.REFERENCE_VALID),
                criterion,
            )
        )

    def get_position_reference_status(
        self,
        *,
        station_id: StationId,
        device_id: DeviceId,
        security_context: SecurityContext,
    ) -> PositionReferenceStatus:
        state, capabilities = self._read_authorized_device(
            station_id=station_id,
            device_id=device_id,
            security_context=security_context,
        )
        return PositionReferenceStatus(
            state=state,
            calibration_supported=DeviceCapabilityName.REFERENCE_CALIBRATION
            in {capability.name for capability in capabilities},
            classification=self._classification,
        )

    def prepare_reference_calibration(
        self,
        *,
        station_id: StationId,
        device_id: DeviceId,
        security_context: SecurityContext,
    ) -> ReferenceCalibrationPreparation:
        state, capabilities = self._read_authorized_device(
            station_id=station_id,
            device_id=device_id,
            security_context=security_context,
        )
        capability_names = {capability.name for capability in capabilities}
        if DeviceCapabilityName.REFERENCE_CALIBRATION not in capability_names:
            raise HardwareRecoveryNotAccessibleError()

        operation = DeviceOperation(
            device_id=device_id,
            operation_type=DeviceOperationType.REFERENCE_CALIBRATION,
        )
        proposal = RecoveryProposal(
            target=RecoveryTarget(device_id=device_id, station_id=station_id),
            problem=_position_reference_problem(state),
            evidence=(
                RecoveryEvidence(
                    reference="position-reference-status",
                    summary=_position_reference_evidence(state),
                ),
            ),
            proposed_action=operation,
            preconditions=tuple(
                RecoveryPrecondition(condition_type)
                for condition_type in RecoveryPreconditionType
            ),
            requires_approval=True,
            expected_effect=(
                "Restore a valid position reference within the configured tolerance"
            ),
            verification_plan=self._verification_plan,
        )
        return ReferenceCalibrationPreparation(
            proposal=proposal,
            precondition_evaluations=evaluate_recovery_preconditions(
                proposal.preconditions, state
            ),
            classification=self._classification,
        )

    def _read_authorized_device(
        self,
        *,
        station_id: StationId,
        device_id: DeviceId,
        security_context: SecurityContext,
    ) -> tuple[DeviceState, tuple[DeviceCapability, ...]]:
        if not isinstance(station_id, StationId):
            raise TypeError("station_id must be a StationId")
        if not isinstance(device_id, DeviceId):
            raise TypeError("device_id must be a DeviceId")
        if not isinstance(security_context, SecurityContext):
            raise TypeError("security_context must be a SecurityContext")
        if security_context.clearance < self._classification:
            raise HardwareRecoveryNotAccessibleError()
        try:
            state = self._physical_devices.read_state(device_id)
            capabilities = self._physical_devices.inspect_capabilities(device_id)
        except (TypeError, ValueError) as error:
            raise HardwareRecoveryNotAccessibleError() from error
        if state.device_id != device_id or state.station_id != station_id:
            raise HardwareRecoveryNotAccessibleError()
        if DeviceCapabilityName.POSITION_REFERENCE_STATUS not in {
            capability.name for capability in capabilities
        }:
            raise HardwareRecoveryNotAccessibleError()
        return state, capabilities

    @property
    def position_deviation_tolerance_mm(self) -> float:
        criterion = self._verification_plan.criteria[1]
        assert criterion.maximum_abs_deviation is not None
        return criterion.maximum_abs_deviation


def _position_reference_problem(state: DeviceState) -> str:
    if state.reference_valid is False:
        return "Position reference is invalid"
    return "Position reference requires controlled calibration assessment"


def _position_reference_evidence(state: DeviceState) -> str:
    deviation = (
        "unavailable"
        if state.position_deviation is None
        else f"{state.position_deviation:.2f} mm"
    )
    return (
        f"reference_valid={state.reference_valid}; "
        f"position_deviation={deviation}; "
        f"operational_state={state.operational_state}"
    )


class HardwareRecoveryExecutionService:
    """Execute one already-approved bounded recovery through the closed-loop use case."""

    def __init__(
        self,
        *,
        preparation: HardwareRecoveryPreparationService,
        physical_devices: PhysicalDevicePort,
        approval_claims: TrustedRecoveryApprovalClaimPort,
    ) -> None:
        self._preparation = preparation
        self._physical_devices = physical_devices
        self._approval_claims = approval_claims

    async def execute_reference_calibration(
        self,
        *,
        run_id: UUID,
        action_id: str,
        station_id: StationId,
        device_id: DeviceId,
        security_context: SecurityContext,
        mcp_execution_permitted: bool,
    ) -> RecoveryResult:
        """Consume approval and delegate the fresh recovery loop to its owner."""
        preparation = self._preparation.prepare_reference_calibration(
            station_id=station_id,
            device_id=device_id,
            security_context=security_context,
        )
        approved = await self._approval_claims.claim_reference_calibration(
            run_id=run_id,
            action_id=action_id,
            station_id=station_id,
            device_id=device_id,
        )
        authorization = TrustedReferenceCalibrationAuthorization(
            security_context=security_context,
            classification=preparation.classification,
            target=preparation.proposal.target,
            approved=approved,
            mcp_execution_permitted=mcp_execution_permitted,
        )
        return ClosedLoopRecoveryService(
            physical_devices=self._physical_devices,
            authorization=authorization,
        ).execute(preparation.proposal)
