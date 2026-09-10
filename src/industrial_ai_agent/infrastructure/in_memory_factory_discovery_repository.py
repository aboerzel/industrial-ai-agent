"""Small deterministic in-memory adapter for local Factory MCP development."""

from industrial_ai_agent.domain.factory_discovery import (
    ProductDiscovery,
    ProductOverview,
    StationDiscovery,
    StationOverview,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.product_history import (
    ProductId,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.domain.security import DataClassification


class InMemoryFactoryDiscoveryRepository:
    def __init__(
        self,
        *,
        stations: tuple[StationDiscovery, ...] | None = None,
        products: tuple[ProductOverview, ...] | None = None,
        station_products: dict[StationId, tuple[ProductId, ...]] | None = None,
    ) -> None:
        self._stations = {
            station.station_id: station
            for station in (stations if stations is not None else _demo_stations())
        }
        source_products = products if products is not None else _demo_products()
        self._products = {
            product.product.product_id: product for product in source_products
        }
        self._station_products = station_products or {
            StationId("S04"): (ProductId("P4711"),)
        }

    def list_stations(self) -> tuple[StationDiscovery, ...]:
        return tuple(
            sorted(self._stations.values(), key=lambda item: item.station_id.value)
        )

    def get_station_overview(self, station_id: StationId) -> StationOverview | None:
        station = self._stations.get(station_id)
        if station is None:
            return None
        recent_product_ids = self._station_products.get(station_id, ())
        return StationOverview(
            station=station,
            recent_product_ids=recent_product_ids,
            recent_products=tuple(
                self._products[product_id].product
                for product_id in recent_product_ids
                if product_id in self._products
            ),
        )

    def list_products(self) -> tuple[ProductDiscovery, ...]:
        return tuple(
            product.product
            for product in sorted(
                self._products.values(), key=lambda item: item.product.product_id.value
            )
        )

    def get_product_overview(self, product_id: ProductId) -> ProductOverview | None:
        return self._products.get(product_id)


def _demo_stations() -> tuple[StationDiscovery, ...]:
    return (
        StationDiscovery(
            station_id=StationId("S04"),
            name="Quality Inspection",
            state=MachineState.FAULTED,
            active_error_code="QUALITY-09",
            classification=DataClassification.CONFIDENTIAL,
        ),
    )


def _demo_products() -> tuple[ProductOverview, ...]:
    return (
        ProductOverview(
            product=ProductDiscovery(
                product_id=ProductId("P4711"),
                latest_station_id=StationId("S04"),
                latest_status=ProductionStepStatus.FAILED,
                latest_error_code="QUALITY-09",
                classification=DataClassification.CONFIDENTIAL,
            ),
            passed_station_ids=(StationId("S01"), StationId("S02"), StationId("S04")),
        ),
    )
