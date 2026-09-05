from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.domain.maintenance_ticket import MaintenanceTicketRequestId
from industrial_ai_agent.domain.maintenance_ticket_repository import (
    MaintenanceTicketRepository,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.tools.tool_contracts import (
    CreateMaintenanceTicketProposalArguments,
)

CreateMaintenanceTicketArguments = CreateMaintenanceTicketProposalArguments


class MaintenanceTicketResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    station_id: str
    summary: str


class MaintenanceTicketCapability:
    def __init__(self, repository: MaintenanceTicketRepository) -> None:
        self._repository = repository

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
