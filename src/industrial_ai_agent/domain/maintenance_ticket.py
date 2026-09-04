from dataclasses import dataclass

from industrial_ai_agent.domain.product_history import StationId


@dataclass(frozen=True, slots=True)
class MaintenanceTicketRequestId:
    value: str

    def __post_init__(self) -> None:
        normalized_value = self.value.strip()
        if not normalized_value:
            raise ValueError("Maintenance ticket request ID must not be empty")
        object.__setattr__(self, "value", normalized_value)


@dataclass(frozen=True, slots=True)
class MaintenanceTicket:
    ticket_id: str
    request_id: MaintenanceTicketRequestId
    station_id: StationId
    summary: str

    def __post_init__(self) -> None:
        normalized_ticket_id = self.ticket_id.strip()
        normalized_summary = self.summary.strip()
        if not normalized_ticket_id:
            raise ValueError("Maintenance ticket ID must not be empty")
        if not normalized_summary:
            raise ValueError("Maintenance ticket summary must not be empty")
        object.__setattr__(self, "ticket_id", normalized_ticket_id)
        object.__setattr__(self, "summary", normalized_summary)
