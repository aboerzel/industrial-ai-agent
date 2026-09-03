from collections.abc import Iterable

from industrial_ai_agent.domain.machine_status import MachineState, MachineStatus
from industrial_ai_agent.domain.product_history import StationId


class InMemoryMachineStatusRepository:
    def __init__(self, statuses: Iterable[MachineStatus] | None = None) -> None:
        source = statuses if statuses is not None else _create_demo_statuses()
        self._statuses = {status.station_id: status for status in source}

    def get_machine_status(self, station_id: StationId) -> MachineStatus | None:
        return self._statuses.get(station_id)


def _create_demo_statuses() -> tuple[MachineStatus, ...]:
    return (
        MachineStatus(
            station_id=StationId("S04"),
            state=MachineState.FAULTED,
            active_error_code="E-STOP-17",
        ),
        MachineStatus(
            station_id=StationId("S12"),
            state=MachineState.RUNNING,
        ),
    )
