"""Small classified projections used for factory discovery and orientation."""

from dataclasses import dataclass

from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.product_history import (
    ProductId,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.domain.security import DataClassification


@dataclass(frozen=True, slots=True)
class StationDiscovery:
    station_id: StationId
    name: str
    state: MachineState | None
    active_error_code: str | None
    classification: DataClassification


@dataclass(frozen=True, slots=True)
class StationOverview:
    station: StationDiscovery
    recent_product_ids: tuple[ProductId, ...]


@dataclass(frozen=True, slots=True)
class ProductDiscovery:
    product_id: ProductId
    latest_station_id: StationId | None
    latest_status: ProductionStepStatus | None
    latest_error_code: str | None
    classification: DataClassification


@dataclass(frozen=True, slots=True)
class ProductOverview:
    product: ProductDiscovery
    passed_station_ids: tuple[StationId, ...]
