from threading import Lock

from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicket,
    MaintenanceTicketId,
    MaintenanceTicketRequestId,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification


class InMemoryMaintenanceTicketRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tickets_by_request_id: dict[
            MaintenanceTicketRequestId, MaintenanceTicket
        ] = {}

    def create_maintenance_ticket(
        self,
        request_id: MaintenanceTicketRequestId,
        station_id: StationId,
        summary: str,
    ) -> MaintenanceTicket:
        with self._lock:
            existing_ticket = self._tickets_by_request_id.get(request_id)
            if existing_ticket is not None:
                return existing_ticket

            ticket = MaintenanceTicket(
                ticket_id=f"MT-{len(self._tickets_by_request_id) + 1:012X}",
                request_id=request_id,
                station_id=station_id,
                summary=summary,
                status="OPEN",
                classification=DataClassification.CONFIDENTIAL,
            )
            self._tickets_by_request_id[request_id] = ticket
            return ticket

    def get_maintenance_ticket(
        self, ticket_id: MaintenanceTicketId
    ) -> MaintenanceTicket | None:
        with self._lock:
            return next(
                (
                    ticket
                    for ticket in self._tickets_by_request_id.values()
                    if ticket.ticket_id == ticket_id.value
                ),
                None,
            )

    def get_maintenance_ticket_by_request_id(
        self, request_id: MaintenanceTicketRequestId
    ) -> MaintenanceTicket | None:
        with self._lock:
            return self._tickets_by_request_id.get(request_id)

    @property
    def tickets(self) -> tuple[MaintenanceTicket, ...]:
        with self._lock:
            return tuple(self._tickets_by_request_id.values())
