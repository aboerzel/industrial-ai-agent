from industrial_ai_agent.domain.machine_status import MachineState, MachineStatus
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import (
    InMemoryMachineStatusRepository,
)
from industrial_ai_agent.tools.machine_status import (
    MachineStatusCapability,
    MachineStatusResult,
)


def create_capability() -> MachineStatusCapability:
    return MachineStatusCapability(InMemoryMachineStatusRepository())


def test_get_machine_status_returns_faulted_s04() -> None:
    result = create_capability().get_machine_status("S04")

    assert isinstance(result, MachineStatusResult)
    assert result == MachineStatusResult(
        station_id="S04",
        found=True,
        state=MachineState.FAULTED,
        active_error_code="E-STOP-17",
    )


def test_get_machine_status_returns_running_s12_without_error() -> None:
    result = create_capability().get_machine_status("S12")

    assert result == MachineStatusResult(
        station_id="S12",
        found=True,
        state=MachineState.RUNNING,
        active_error_code=None,
    )


def test_get_machine_status_returns_structured_not_found_result() -> None:
    result = create_capability().get_machine_status("S99")

    assert result == MachineStatusResult(
        station_id="S99",
        found=False,
        state=None,
        active_error_code=None,
    )


def test_repository_accepts_custom_machine_statuses() -> None:
    custom_status = MachineStatus(
        station_id=StationId("S21"),
        state=MachineState.MAINTENANCE,
    )
    repository = InMemoryMachineStatusRepository((custom_status,))

    assert repository.get_machine_status(StationId("S21")) == custom_status
    assert repository.get_machine_status(StationId("S04")) is None
