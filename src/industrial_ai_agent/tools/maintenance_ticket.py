import asyncio
from collections.abc import Callable
from functools import partial
from hashlib import sha256
from threading import Event
from uuid import UUID

import anyio
from anyio.lowlevel import checkpoint
from anyio.to_thread import run_sync
from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.application.action_approval import (
    MaintenanceTicketApprovalClaim,
    TrustedActionApprovalClaimPort,
)
from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicketId,
    MaintenanceTicketRequestId,
)
from industrial_ai_agent.domain.maintenance_ticket_repository import (
    MaintenanceTicketRepository,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.tools.tool_contracts import (
    CreateMaintenanceTicketProposalArguments,
)

CreateMaintenanceTicketArguments = CreateMaintenanceTicketProposalArguments


class MaintenanceTicketResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    station_id: str
    summary: str


class MaintenanceTicketLookupResult(BaseModel):
    """Bounded public projection for one ticket already visible to the caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    found: bool
    status: str | None = None
    station_id: str | None = None
    summary: str | None = None
    classification: DataClassification = DataClassification.CONFIDENTIAL


class MaintenanceTicketCapability:
    def __init__(
        self,
        repository: MaintenanceTicketRepository,
        *,
        approval_claims: TrustedActionApprovalClaimPort | None = None,
    ) -> None:
        self._repository = repository
        self._approval_claims = approval_claims

    def get_maintenance_ticket(self, ticket_id: str) -> MaintenanceTicketLookupResult:
        requested_ticket_id = MaintenanceTicketId(ticket_id)
        ticket = self._repository.get_maintenance_ticket(requested_ticket_id)
        if ticket is None:
            # The repository query is RLS-filtered. A hidden ticket deliberately has
            # the same result as an unknown ticket.
            return MaintenanceTicketLookupResult(
                ticket_id=requested_ticket_id.value,
                found=False,
            )
        return MaintenanceTicketLookupResult(
            ticket_id=ticket.ticket_id,
            found=True,
            status=ticket.status,
            station_id=ticket.station_id.value,
            summary=ticket.summary,
            classification=ticket.classification,
        )

    async def create_maintenance_ticket(
        self,
        request_id: str,
        station_id: str,
        summary: str,
        *,
        run_id: UUID,
        security_context: SecurityContext,
    ) -> MaintenanceTicketResult:
        if (
            self._approval_claims is None
            or security_context.clearance < DataClassification.CONFIDENTIAL
        ):
            raise PermissionError("Protected action is not authorized")
        station = StationId(station_id)
        request = MaintenanceTicketRequestId(request_id)
        claim = MaintenanceTicketApprovalClaim(run_id, request.value, station, summary)
        # request_id is now the authoritative approval generation, not the model ID.
        idempotency_id = MaintenanceTicketRequestId(
            sha256(f"{run_id}:{request.value}".encode()).hexdigest()
        )
        await checkpoint()
        if await self._approval_claims.claim_approved_action(claim, security_context):
            ticket = await _run_owned_ticket_io(
                partial(
                    self._repository.create_maintenance_ticket,
                    idempotency_id,
                    station,
                    summary,
                )
            )
        elif await self._approval_claims.is_consumed_approved_action(
            claim, security_context
        ):
            # A consumed claim can authorize a read of its existing result only.
            ticket = await _run_owned_ticket_io(
                partial(
                    self._repository.get_maintenance_ticket_by_request_id,
                    idempotency_id,
                )
            )
        else:
            raise PermissionError("Protected action is not authorized")
        if ticket is None or ticket.station_id != station or ticket.summary != summary:
            raise PermissionError("Protected action is not authorized")
        return MaintenanceTicketResult(
            ticket_id=ticket.ticket_id,
            station_id=ticket.station_id.value,
            summary=ticket.summary,
        )


async def _run_owned_ticket_io[T](operation: Callable[[], T]) -> T:
    """Keep bounded blocking I/O owned until completion, including on cancellation."""
    # A consumed approval does not require dispatch if cancellation is already known.
    await checkpoint()
    cancelled = Event()

    def invoke() -> T:
        # Cancellation while waiting for pool capacity must not start a new write.
        if cancelled.is_set():
            raise asyncio.CancelledError
        return operation()

    worker = asyncio.create_task(
        run_sync(invoke, abandon_on_cancel=False),
        name="maintenance-ticket-owned-io",
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled.set()
        # Native Task.cancel() also needs shielding; AnyIO's worker shield alone
        # protects cancellation scopes, not a direct cancellation of its task.
        with anyio.CancelScope(shield=True):
            while not worker.done():
                try:
                    await asyncio.wait({worker})
                except asyncio.CancelledError:
                    continue
            if not worker.cancelled():
                worker.exception()  # Retrieve a late failure without losing cancellation.
        raise
