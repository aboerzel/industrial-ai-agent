"""Read-only, agent-facing factory discovery capabilities."""

from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.domain.factory_discovery_repository import (
    FactoryDiscoveryRepository,
)
from industrial_ai_agent.domain.security import (
    DataClassification,
    effective_data_classification,
)
from industrial_ai_agent.tools.tool_contracts import (
    ProductIdentifier,
    StationIdentifier,
)


class StationDiscoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    station_id: str
    name: str
    state: str | None
    active_error_code: str | None
    classification: DataClassification


class StationListResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stations: tuple[StationDiscoveryResult, ...]
    classification: DataClassification


class ProductDiscoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str
    latest_station_id: str | None
    latest_status: str | None
    latest_error_code: str | None
    classification: DataClassification


class StationOverviewResult(StationDiscoveryResult):
    found: bool
    recent_product_ids: tuple[str, ...] = ()
    recent_products: tuple[ProductDiscoveryResult, ...] = ()


class ProductListResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    products: tuple[ProductDiscoveryResult, ...]
    classification: DataClassification


class ProductOverviewResult(ProductDiscoveryResult):
    found: bool
    passed_station_ids: tuple[str, ...] = ()


class FactoryDiscoveryCapability:
    """Expose bounded factory orientation without leaking persistence queries."""

    def __init__(self, repository: FactoryDiscoveryRepository) -> None:
        self._repository = repository

    def list_stations(self) -> StationListResult:
        stations = self._repository.list_stations()
        return StationListResult(
            stations=tuple(_station_result(item) for item in stations),
            classification=_collection_classification(
                tuple(item.classification for item in stations)
            ),
        )

    def get_station_overview(
        self, station_id: StationIdentifier
    ) -> StationOverviewResult:
        from industrial_ai_agent.domain.product_history import StationId

        requested_station_id = StationId(station_id)
        overview = self._repository.get_station_overview(requested_station_id)
        if overview is None:
            return StationOverviewResult(
                station_id=requested_station_id.value,
                name="",
                state=None,
                active_error_code=None,
                found=False,
                classification=DataClassification.PUBLIC,
            )
        station = _station_result(overview.station)
        return StationOverviewResult(
            **station.model_dump(),
            found=True,
            recent_product_ids=tuple(
                product_id.value for product_id in overview.recent_product_ids
            ),
            recent_products=tuple(
                _product_result(product) for product in overview.recent_products
            ),
        )

    def list_products(self) -> ProductListResult:
        products = self._repository.list_products()
        return ProductListResult(
            products=tuple(_product_result(item) for item in products),
            classification=_collection_classification(
                tuple(item.classification for item in products)
            ),
        )

    def get_product_overview(
        self, product_id: ProductIdentifier
    ) -> ProductOverviewResult:
        from industrial_ai_agent.domain.product_history import ProductId

        requested_product_id = ProductId(product_id)
        overview = self._repository.get_product_overview(requested_product_id)
        if overview is None:
            return ProductOverviewResult(
                product_id=requested_product_id.value,
                latest_station_id=None,
                latest_status=None,
                latest_error_code=None,
                found=False,
                classification=DataClassification.PUBLIC,
            )
        product = _product_result(overview.product)
        return ProductOverviewResult(
            **product.model_dump(),
            found=True,
            passed_station_ids=tuple(
                station_id.value for station_id in overview.passed_station_ids
            ),
        )


def _station_result(item) -> StationDiscoveryResult:
    return StationDiscoveryResult(
        station_id=item.station_id.value,
        name=item.name,
        state=item.state.value if item.state is not None else None,
        active_error_code=item.active_error_code,
        classification=item.classification,
    )


def _product_result(item) -> ProductDiscoveryResult:
    return ProductDiscoveryResult(
        product_id=item.product_id.value,
        latest_station_id=(
            item.latest_station_id.value if item.latest_station_id is not None else None
        ),
        latest_status=item.latest_status.value
        if item.latest_status is not None
        else None,
        latest_error_code=item.latest_error_code,
        classification=item.classification,
    )


def _collection_classification(
    classifications: tuple[DataClassification, ...],
) -> DataClassification:
    return (
        effective_data_classification(*classifications)
        if classifications
        else DataClassification.PUBLIC
    )
