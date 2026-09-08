from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicketId,
    MaintenanceTicketRequestId,
)
from industrial_ai_agent.domain.maintenance_ticket_repository import (
    MaintenanceTicketRepository,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification
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
    def __init__(self, repository: MaintenanceTicketRepository) -> None:
        self._repository = repository

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

    def create_maintenance_ticket(
        self,
        request_id: str,
        station_id: str,
        summary: str,
    ) -> MaintenanceTicketResult:
        ticket = self._repository.create_maintenance_ticket(
            MaintenanceTicketRequestId(request_id),
            StationId(station_id),
            summary,
        )
        return MaintenanceTicketResult(
            ticket_id=ticket.ticket_id,
            station_id=ticket.station_id.value,
            summary=ticket.summary,
        )
