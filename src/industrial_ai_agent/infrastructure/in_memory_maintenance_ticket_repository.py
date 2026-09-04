from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicket,
    MaintenanceTicketRequestId,
)
from industrial_ai_agent.domain.product_history import StationId


class InMemoryMaintenanceTicketRepository:
    def __init__(self) -> None:
        self._tickets_by_request_id: dict[
            MaintenanceTicketRequestId, MaintenanceTicket
        ] = {}

    def create_maintenance_ticket(
        self,
        request_id: MaintenanceTicketRequestId,
        station_id: StationId,
        summary: str,
    ) -> MaintenanceTicket:
        existing_ticket = self._tickets_by_request_id.get(request_id)
        if existing_ticket is not None:
            return existing_ticket

        ticket = MaintenanceTicket(
            ticket_id=f"MT-{len(self._tickets_by_request_id) + 1:04d}",
            request_id=request_id,
            station_id=station_id,
            summary=summary,
        )
        self._tickets_by_request_id[request_id] = ticket
        return ticket

    @property
    def tickets(self) -> tuple[MaintenanceTicket, ...]:
        return tuple(self._tickets_by_request_id.values())
