"""Inner contracts for consuming the existing persisted HITL action approvals."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.domain.physical_device import DeviceId
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification, SecurityContext

type ProtectedActionName = Literal[
    "create_maintenance_ticket", "execute_reference_calibration"
]


@dataclass(frozen=True, slots=True)
class MaintenanceTicketApprovalClaim:
    run_id: UUID
    action_id: str
    station_id: StationId
    summary: str


@dataclass(frozen=True, slots=True)
class ReferenceCalibrationApprovalClaim:
    run_id: UUID
    action_id: str
    station_id: StationId
    device_id: DeviceId


type ProtectedActionApprovalClaim = (
    MaintenanceTicketApprovalClaim | ReferenceCalibrationApprovalClaim
)


class TrustedActionApprovalClaimPort(Protocol):
    async def claim_approved_action(
        self, claim: ProtectedActionApprovalClaim, security_context: SecurityContext
    ) -> bool:
        """Consume exactly one accessible, approved, action-bound persisted claim."""


def is_action_profile_authorized(
    action: str, classification: DataClassification, run_profile: AgentRunProfile
) -> bool:
    """Share the existing API resume policy with the execution boundary."""
    if classification is not DataClassification.CONFIDENTIAL:
        return False
    if action == "create_maintenance_ticket":
        return run_profile is AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    return action == "execute_reference_calibration" and run_profile in {
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        AgentRunProfile.CONFIDENTIAL_RECOVERY,
    }
