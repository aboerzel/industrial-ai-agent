from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.domain.product_history import StationId


class MachineState(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAULTED = "FAULTED"
    MAINTENANCE = "MAINTENANCE"


@dataclass(frozen=True, slots=True)
class MachineStatus:
    station_id: StationId
    state: MachineState
    active_error_code: str | None = None
