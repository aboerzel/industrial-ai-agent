"""Port for bounded, clearance-filtered factory orientation projections."""

from typing import Protocol

from industrial_ai_agent.domain.factory_discovery import (
    ProductDiscovery,
    ProductOverview,
    StationDiscovery,
    StationOverview,
)
from industrial_ai_agent.domain.product_history import ProductId, StationId


class FactoryDiscoveryRepository(Protocol):
    def list_stations(self) -> tuple[StationDiscovery, ...]: ...

    def get_station_overview(self, station_id: StationId) -> StationOverview | None: ...

    def list_products(self) -> tuple[ProductDiscovery, ...]: ...

    def get_product_overview(self, product_id: ProductId) -> ProductOverview | None: ...
