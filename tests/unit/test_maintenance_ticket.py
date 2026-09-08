from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability


def test_get_maintenance_ticket_returns_only_the_existing_ticket_projection() -> None:
    repository = InMemoryMaintenanceTicketRepository()
    capability = MaintenanceTicketCapability(repository)
    created = capability.create_maintenance_ticket(
        request_id="read-projection",
        station_id="S04",
        summary="Inspect QUALITY-09",
    )
    tickets_before_read = repository.tickets

    result = capability.get_maintenance_ticket(created.ticket_id)

    assert result.model_dump(mode="json") == {
        "ticket_id": created.ticket_id,
        "found": True,
        "status": "OPEN",
        "station_id": "S04",
        "summary": "Inspect QUALITY-09",
        "classification": 2,
    }
    assert repository.tickets == tickets_before_read


def test_get_maintenance_ticket_returns_the_neutral_not_found_projection() -> None:
    capability = MaintenanceTicketCapability(InMemoryMaintenanceTicketRepository())

    result = capability.get_maintenance_ticket("MT-FFFFFFFFFFFF")

    assert result.model_dump(mode="json") == {
        "ticket_id": "MT-FFFFFFFFFFFF",
        "found": False,
        "status": None,
        "station_id": None,
        "summary": None,
        "classification": 2,
    }
