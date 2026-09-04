from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification


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
    classification: DataClassification = DataClassification.CONFIDENTIAL

    def __post_init__(self) -> None:
        if not isinstance(self.classification, DataClassification):
            raise TypeError("Unknown machine status classification")
