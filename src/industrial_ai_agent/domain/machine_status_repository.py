from typing import Protocol

from industrial_ai_agent.domain.machine_status import MachineStatus
from industrial_ai_agent.domain.product_history import StationId


class MachineStatusRepository(Protocol):
    def get_machine_status(self, station_id: StationId) -> MachineStatus | None: ...
