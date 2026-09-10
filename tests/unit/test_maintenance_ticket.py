import pytest

from industrial_ai_agent.domain.maintenance_ticket import MaintenanceTicketId
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.tool_contracts import GetMaintenanceTicketArguments


def test_maintenance_ticket_id_accepts_seeded_and_legacy_grammar() -> None:
    assert MaintenanceTicketId("MT-S02-20260117").value == "MT-S02-20260117"
    assert MaintenanceTicketId("MT-6EA0DEF5515A").value == "MT-6EA0DEF5515A"
    assert MaintenanceTicketId("MT-S99-20991231").value == "MT-S99-20991231"


@pytest.mark.parametrize("ticket_id", ("MT-S02-20260117", "MT-6EA0DEF5515A"))
def test_maintenance_ticket_tool_contract_accepts_supported_grammar(
    ticket_id: str,
) -> None:
    assert GetMaintenanceTicketArguments(ticket_id=ticket_id).ticket_id == ticket_id


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
