"""Trusted recovery-approval adapter over the existing persisted run lifecycle."""

from uuid import UUID

from industrial_ai_agent.application.hardware_recovery import (
    TrustedRecoveryApprovalClaimPort,
)
from industrial_ai_agent.domain.physical_device import DeviceId
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.infrastructure.api.run_store import AgentRunStore


class AgentRunStoreRecoveryApprovalPort(TrustedRecoveryApprovalClaimPort):
    """Consume one server-persisted approved hardware action bound to its run."""

    def __init__(self, run_store: AgentRunStore) -> None:
        self._run_store = run_store

    async def claim_reference_calibration(
        self,
        *,
        run_id: UUID,
        action_id: str,
        station_id: StationId,
        device_id: DeviceId,
    ) -> bool:
        return await self._run_store.claim_reference_calibration_approval(
            run_id,
            action_id=action_id,
            station_id=station_id.value,
            device_id=device_id.value,
        )
