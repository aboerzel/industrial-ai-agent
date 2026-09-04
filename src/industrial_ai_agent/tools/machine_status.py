from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.machine_status_repository import MachineStatusRepository
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification


class MachineStatusResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    station_id: str
    found: bool
    state: MachineState | None = None
    active_error_code: str | None = None
    classification: DataClassification = DataClassification.CONFIDENTIAL


class MachineStatusCapability:
    def __init__(self, repository: MachineStatusRepository) -> None:
        self._repository = repository

    def get_machine_status(self, station_id: str) -> MachineStatusResult:
        requested_station_id = StationId(station_id)
        status = self._repository.get_machine_status(requested_station_id)

        if status is None:
            return MachineStatusResult(
                station_id=requested_station_id.value,
                found=False,
            )

        return MachineStatusResult(
            station_id=status.station_id.value,
            found=True,
            state=status.state,
            active_error_code=status.active_error_code,
            classification=status.classification,
        )
