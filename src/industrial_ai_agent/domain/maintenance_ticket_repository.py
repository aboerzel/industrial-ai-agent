from typing import Protocol

from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicket,
    MaintenanceTicketId,
    MaintenanceTicketRequestId,
)
from industrial_ai_agent.domain.product_history import StationId


class MaintenanceTicketRepository(Protocol):
    def get_maintenance_ticket(
        self, ticket_id: MaintenanceTicketId
    ) -> MaintenanceTicket | None: ...

    def create_maintenance_ticket(
        self,
        request_id: MaintenanceTicketRequestId,
        station_id: StationId,
        summary: str,
    ) -> MaintenanceTicket: ...
