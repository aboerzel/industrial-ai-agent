import re
from dataclasses import dataclass

from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification


@dataclass(frozen=True, slots=True)
class MaintenanceTicketRequestId:
    value: str

    def __post_init__(self) -> None:
        normalized_value = self.value.strip()
        if not normalized_value:
            raise ValueError("Maintenance ticket request ID must not be empty")
        object.__setattr__(self, "value", normalized_value)


@dataclass(frozen=True, slots=True)
class MaintenanceTicketId:
    value: str

    def __post_init__(self) -> None:
        normalized_value = self.value.strip()
        if not normalized_value:
            raise ValueError("Maintenance ticket ID must not be empty")
        if re.fullmatch(r"MT-[A-F0-9]{12}", normalized_value) is None:
            raise ValueError("Maintenance ticket ID has an invalid format")
        object.__setattr__(self, "value", normalized_value)


@dataclass(frozen=True, slots=True)
class MaintenanceTicket:
    ticket_id: str
    request_id: MaintenanceTicketRequestId
    station_id: StationId
    summary: str
    status: str
    classification: DataClassification

    def __post_init__(self) -> None:
        normalized_ticket_id = self.ticket_id.strip()
        normalized_summary = self.summary.strip()
        normalized_status = self.status.strip()
        if not normalized_ticket_id:
            raise ValueError("Maintenance ticket ID must not be empty")
        if not normalized_summary:
            raise ValueError("Maintenance ticket summary must not be empty")
        if not normalized_status:
            raise ValueError("Maintenance ticket status must not be empty")
        if not isinstance(self.classification, DataClassification):
            raise TypeError("Unknown maintenance ticket classification")
        object.__setattr__(self, "ticket_id", normalized_ticket_id)
        object.__setattr__(self, "summary", normalized_summary)
        object.__setattr__(self, "status", normalized_status)
