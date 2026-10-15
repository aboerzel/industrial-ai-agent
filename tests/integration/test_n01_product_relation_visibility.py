"""Real RLS projections when independently visible events reference hidden stations."""

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, joinedload

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    _append_observation_identifiers,
)
from industrial_ai_agent.domain.factory_discovery import (
    ProductDiscovery,
    ProductOverview,
)
from industrial_ai_agent.domain.product_history import ProductHistory, ProductId
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    create_factory_mcp_server,
)
from industrial_ai_agent.infrastructure.in_memory_factory_discovery_repository import (
    InMemoryFactoryDiscoveryRepository,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.infrastructure.persistence.models import (
    FactoryRecord,
    ProductEventRecord,
    ProductRecord,
    StationRecord,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlFactoryDiscoveryRepository,
    PostgreSqlMachineStatusRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.factory_discovery import (
    FactoryDiscoveryCapability,
    ProductListResult,
    ProductOverviewResult,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import (
    ProductHistoryCapability,
    ProductHistoryResult,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("FACTORY_DATABASE_URL")
    or not os.getenv("FACTORY_DATABASE_ADMIN_URL"),
    reason="requires disposable PostgreSQL app/admin fixtures",
)
PRODUCT = "P6201"
ALL_HIDDEN = "P6202"
HIDDEN_PRODUCT = "P6203"
STATIONS = ("S91", "S92", "S93", "S94")
START = datetime(2026, 10, 1, tzinfo=UTC)
ROUTE = (0, 1, 2, 0, 3)
SCHEMAS = {
    "list_products": ProductListResult,
    "get_product_overview": ProductOverviewResult,
    "get_product_history": ProductHistoryResult,
}


def context(clearance):
    return SecurityContext("synthetic-n01-reader", ("reader",), clearance, True)


@pytest.fixture(scope="module")
def mixed_rows():
    """Admin only prepares/removes synthetic rows; every tested read uses factory_app."""
    admin = create_engine(os.environ["FACTORY_DATABASE_ADMIN_URL"])
    factory = PostgreSqlSessionFactory(os.environ["FACTORY_DATABASE_URL"])
    factory_id = uuid4()
    products = {code: uuid4() for code in (PRODUCT, ALL_HIDDEN, HIDDEN_PRODUCT)}
    stations = tuple(uuid4() for _ in STATIONS)
    try:
        with Session(admin) as session, session.begin():
            session.add(
                FactoryRecord(
                    id=factory_id,
                    code="N01-SYNTHETIC",
                    name="N01 fixture",
                    classification=0,
                )
            )
            session.flush()
            session.add_all(
                [
                    StationRecord(
                        id=identifier,
                        factory_id=factory_id,
                        code=code,
                        name=f"N01-PRIVATE-NAME-{rank}",
                        classification=rank,
                    )
                    for rank, (identifier, code) in enumerate(
                        zip(stations, STATIONS, strict=True)
                    )
                ]
            )
            session.add_all(
                [
                    ProductRecord(
                        id=identifier,
                        factory_id=factory_id,
                        product_code=code,
                        classification=3 if code == HIDDEN_PRODUCT else 0,
                    )
                    for code, identifier in products.items()
                ]
            )
            session.flush()
            session.add_all(
                [
                    ProductEventRecord(
                        id=uuid4(),
                        product_id=products[PRODUCT],
                        station_id=stations[rank],
                        event_at=START + timedelta(minutes=index),
                        status="FAILED",
                        error_code=f"N01-FAULT-{rank}",
                        classification=0,
                    )
                    for index, rank in enumerate(ROUTE)
                ]
            )
            session.add(
                ProductEventRecord(
                    id=uuid4(),
                    product_id=products[ALL_HIDDEN],
                    station_id=stations[3],
                    event_at=START,
                    status="FAILED",
                    error_code="N01-FAULT-3",
                    classification=0,
                )
            )
            session.add(
                ProductEventRecord(
                    id=uuid4(),
                    product_id=products[HIDDEN_PRODUCT],
                    station_id=stations[0],
                    event_at=START,
                    status="FAILED",
                    error_code="N01-FAULT-0",
                    classification=2,
                )
            )
        yield factory, admin, products, stations
    finally:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM product_event WHERE product_id IN (SELECT id FROM product WHERE factory_id=:id)"
                ),
                {"id": factory_id},
            )
            for table in ("product", "station", "factory"):
                connection.execute(
                    text(
                        f"DELETE FROM {table} WHERE {'id' if table == 'factory' else 'factory_id'}=:id"
                    ),
                    {"id": factory_id},
                )
        factory.dispose()
        admin.dispose()


def server_for(factory, clearance):
    security = context(clearance)
    return create_factory_mcp_server(
        product_history=ProductHistoryCapability(
            PostgreSqlProductHistoryRepository(factory, security)
        ),
        machine_status=MachineStatusCapability(
            PostgreSqlMachineStatusRepository(factory, security)
        ),
        factory_discovery=FactoryDiscoveryCapability(
            PostgreSqlFactoryDiscoveryRepository(factory, security)
        ),
    )


def call(server, tool, product=PRODUCT):
    response = asyncio.run(
        server.call_tool(
            tool, {} if tool == "list_products" else {"product_id": product}
        )
    )
    assert not response.is_error
    payload = response.structured_content
    SCHEMAS[tool].model_validate(payload)
    if tool == "list_products":
        return next(
            item for item in payload["products"] if item["product_id"] == product
        ), payload
    return payload, payload


@pytest.mark.parametrize("clearance", tuple(DataClassification))
@pytest.mark.parametrize("tool", tuple(SCHEMAS))
def test_n01_real_mcp_projections_filter_hidden_relations(
    mixed_rows, clearance, tool, caplog
):
    caplog.set_level(logging.DEBUG)
    factory, _, _, _ = mixed_rows
    server = server_for(factory, clearance)
    visible = [(index, rank) for index, rank in enumerate(ROUTE) if rank <= clearance]
    for product in (PRODUCT, ALL_HIDDEN):
        data, payload = call(server, tool, product)
        expected = (
            visible
            if product == PRODUCT
            else ([(0, 3)] if clearance == DataClassification.RESTRICTED else [])
        )
        assert data["product_id"] == product
        assert data["classification"] == max((rank for _, rank in expected), default=0)
        if tool == "get_product_history":
            assert data["found"] is True
            assert data["steps"] == [
                {
                    "station_id": STATIONS[rank],
                    "timestamp": (START + timedelta(minutes=index))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "status": "FAILED",
                    "error_code": f"N01-FAULT-{rank}",
                }
                for index, rank in expected
            ]
        else:
            assert data["latest_station_id"] == (
                STATIONS[expected[-1][1]] if expected else None
            )
            assert data["latest_status"] == ("FAILED" if expected else None)
            assert data["latest_error_code"] == (
                f"N01-FAULT-{expected[-1][1]}" if expected else None
            )
            if tool == "get_product_overview":
                assert data["found"] is True
                assert data["passed_station_ids"] == [
                    STATIONS[rank] for _, rank in expected
                ]
        references = []
        _append_observation_identifiers(references, tool, json.dumps(payload))
        encoded = json.dumps(
            {
                "payload": payload,
                "references": [item.model_dump(mode="json") for item in references],
            }
        )
        for rank in range(int(clearance) + 1, 4):
            for marker in (
                STATIONS[rank],
                f"N01-PRIVATE-NAME-{rank}",
                f"N01-FAULT-{rank}",
            ):
                assert marker not in encoded
                assert marker not in caplog.text
        assert "AttributeError" not in caplog.text
        assert data["classification"] <= clearance
        if tool == "list_products":
            assert (
                HIDDEN_PRODUCT in {item["product_id"] for item in payload["products"]}
            ) is (clearance == DataClassification.RESTRICTED)


@pytest.mark.parametrize("clearance", tuple(DataClassification))
def test_n01_rls_independently_filters_rows_and_related_station(mixed_rows, clearance):
    factory, _, products, _ = mixed_rows
    with factory.session(context(clearance)) as session:
        assert (
            session.execute(
                text(
                    "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname=current_user"
                )
            ).scalar_one()
            is False
        )
        visible_stations = tuple(
            session.scalars(
                select(StationRecord).where(StationRecord.code.in_(STATIONS))
            )
        )
        assert {s.code for s in visible_stations} == set(STATIONS[: int(clearance) + 1])
        events = tuple(
            session.scalars(
                select(ProductEventRecord)
                .options(joinedload(ProductEventRecord.station))
                .where(ProductEventRecord.product_id == products[PRODUCT])
                .order_by(ProductEventRecord.event_at)
            )
        )
        assert len(events) == len(ROUTE)
        assert [e.station is not None for e in events] == [
            rank <= clearance for rank in ROUTE
        ]
        hidden_product_events = tuple(
            session.scalars(
                select(ProductEventRecord).where(
                    ProductEventRecord.product_id == products[HIDDEN_PRODUCT]
                )
            )
        )
        assert len(hidden_product_events) == (
            1 if clearance >= DataClassification.CONFIDENTIAL else 0
        )
    capability = ProductHistoryCapability(
        PostgreSqlProductHistoryRepository(factory, context(clearance))
    )
    hidden = capability.get_product_history(HIDDEN_PRODUCT)
    assert hidden.found is (clearance == DataClassification.RESTRICTED)
    if not hidden.found:
        assert hidden == capability.get_product_history("P6299").model_copy(
            update={"product_id": HIDDEN_PRODUCT}
        )


def test_n01_physical_foreign_keys_remain_nonnullable_and_valid(mixed_rows):
    _, admin, products, _ = mixed_rows
    columns = {
        column["name"]: column for column in inspect(admin).get_columns("product_event")
    }
    assert columns["station_id"]["nullable"] is False
    assert any(
        fk["constrained_columns"] == ["station_id"]
        and fk["referred_table"] == "station"
        for fk in inspect(admin).get_foreign_keys("product_event")
    )
    with admin.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM product_event e LEFT JOIN station s ON s.id=e.station_id WHERE e.product_id=:id AND s.id IS NULL"
                ),
                {"id": products[PRODUCT]},
            ).scalar_one()
            == 0
        )


def test_n01_higher_clearance_monotonically_reveals_relationships(mixed_rows):
    factory, _, _, _ = mixed_rows
    previous = set()
    for clearance in DataClassification:
        history = ProductHistoryCapability(
            PostgreSqlProductHistoryRepository(factory, context(clearance))
        ).get_product_history(PRODUCT)
        current = {step.timestamp for step in history.steps}
        assert previous <= current
        previous = current
    assert len(previous) == len(ROUTE)


def test_n01_reclassification_does_not_hide_the_independent_product(mixed_rows):
    factory, admin, products, stations = mixed_rows
    server = server_for(factory, DataClassification.PUBLIC)
    assert call(server, "get_product_history")[0]["steps"]
    try:
        with admin.begin() as connection:
            connection.execute(
                text("UPDATE station SET classification=2 WHERE id=:id"),
                {"id": stations[0]},
            )
        for tool in SCHEMAS:
            data, _ = call(server, tool)
            assert data["classification"] == 0
            if tool == "get_product_history":
                assert data["found"] is True and data["steps"] == []
            else:
                assert data["latest_station_id"] is None
                assert data["latest_status"] is None
                assert data["latest_error_code"] is None
        with factory.connection(context(DataClassification.PUBLIC)) as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM product WHERE id=:id"),
                    {"id": products[PRODUCT]},
                ).scalar_one()
                == 1
            )
        full, _ = call(
            server_for(factory, DataClassification.RESTRICTED), "get_product_history"
        )
        assert len(full["steps"]) == len(ROUTE)
    finally:
        with admin.begin() as connection:
            connection.execute(
                text("UPDATE station SET classification=0 WHERE id=:id"),
                {"id": stations[0]},
            )


def test_n01_station_overview_uses_the_same_safe_product_projection(mixed_rows):
    factory, _, _, _ = mixed_rows
    response = asyncio.run(
        server_for(factory, DataClassification.PUBLIC).call_tool(
            "get_station_overview", {"station_id": STATIONS[0]}
        )
    )
    assert not response.is_error
    data = response.structured_content
    assert data["recent_product_ids"] == [PRODUCT]
    assert data["recent_products"][0]["latest_station_id"] == STATIONS[0]
    assert data["recent_products"][0]["classification"] == 0
    assert all(identifier not in json.dumps(data) for identifier in STATIONS[1:])


def test_n01_empty_projection_matches_in_memory_contract(mixed_rows):
    factory, _, _, _ = mixed_rows
    product = ProductId(ALL_HIDDEN)
    fake_discovery = FactoryDiscoveryCapability(
        InMemoryFactoryDiscoveryRepository(
            stations=(),
            products=(
                ProductOverview(
                    ProductDiscovery(
                        product, None, None, None, DataClassification.PUBLIC
                    ),
                    (),
                ),
            ),
        )
    )
    postgres_discovery = FactoryDiscoveryCapability(
        PostgreSqlFactoryDiscoveryRepository(
            factory, context(DataClassification.PUBLIC)
        )
    )
    assert fake_discovery.get_product_overview(
        ALL_HIDDEN
    ) == postgres_discovery.get_product_overview(ALL_HIDDEN)
    fake_history = ProductHistoryCapability(
        InMemoryProductHistoryRepository(
            (ProductHistory(product, (), DataClassification.PUBLIC),)
        )
    )
    postgres_history = ProductHistoryCapability(
        PostgreSqlProductHistoryRepository(factory, context(DataClassification.PUBLIC))
    )
    assert fake_history.get_product_history(
        ALL_HIDDEN
    ) == postgres_history.get_product_history(ALL_HIDDEN)
