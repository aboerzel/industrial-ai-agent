from industrial_ai_agent.domain.factory_discovery import (
    ProductDiscovery,
    ProductOverview,
    StationDiscovery,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.product_history import (
    ProductId,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.in_memory_factory_discovery_repository import (
    InMemoryFactoryDiscoveryRepository,
)
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability


def _capability() -> FactoryDiscoveryCapability:
    station = StationDiscovery(
        station_id=StationId("S04"),
        name="Quality Inspection",
        state=MachineState.FAULTED,
        active_error_code="QUALITY-09",
        classification=DataClassification.CONFIDENTIAL,
    )
    product = ProductOverview(
        product=ProductDiscovery(
            product_id=ProductId("P4711"),
            latest_station_id=StationId("S04"),
            latest_status=ProductionStepStatus.FAILED,
            latest_error_code="QUALITY-09",
            classification=DataClassification.CONFIDENTIAL,
        ),
        passed_station_ids=(StationId("S01"), StationId("S02"), StationId("S04")),
    )
    return FactoryDiscoveryCapability(
        InMemoryFactoryDiscoveryRepository(
            stations=(station,),
            products=(product,),
            station_products={StationId("S04"): (ProductId("P4711"),)},
        )
    )


def test_factory_discovery_returns_bounded_station_and_product_projections() -> None:
    capability = _capability()

    stations = capability.list_stations()
    products = capability.list_products()

    assert stations.classification is DataClassification.CONFIDENTIAL
    assert stations.stations[0].model_dump(mode="json") == {
        "station_id": "S04",
        "name": "Quality Inspection",
        "state": "FAULTED",
        "active_error_code": "QUALITY-09",
        "classification": 2,
    }
    assert products.classification is DataClassification.CONFIDENTIAL
    assert products.products[0].latest_status == "FAILED"
    assert products.products[0].latest_station_id == "S04"


def test_factory_discovery_overviews_retain_classification_and_relationships() -> None:
    capability = _capability()

    station = capability.get_station_overview("S04")
    product = capability.get_product_overview("P4711")

    assert station.found is True
    assert station.classification is DataClassification.CONFIDENTIAL
    assert station.recent_product_ids == ("P4711",)
    assert [product.model_dump(mode="json") for product in station.recent_products] == [
        {
            "product_id": "P4711",
            "latest_station_id": "S04",
            "latest_status": "FAILED",
            "latest_error_code": "QUALITY-09",
            "classification": 2,
        }
    ]
    assert product.found is True
    assert product.classification is DataClassification.CONFIDENTIAL
    assert product.passed_station_ids == ("S01", "S02", "S04")


def test_factory_discovery_returns_neutral_not_found_projections() -> None:
    capability = _capability()

    station = capability.get_station_overview("S99")
    product = capability.get_product_overview("P9999")

    assert station.model_dump(mode="json") == {
        "station_id": "S99",
        "name": "",
        "state": None,
        "active_error_code": None,
        "classification": 0,
        "found": False,
        "recent_product_ids": [],
        "recent_products": [],
    }
    assert product.model_dump(mode="json") == {
        "product_id": "P9999",
        "latest_station_id": None,
        "latest_status": None,
        "latest_error_code": None,
        "classification": 0,
        "found": False,
        "passed_station_ids": [],
    }
