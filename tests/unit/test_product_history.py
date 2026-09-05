from datetime import UTC, datetime

import pytest

from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    ProductionStep,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.tools.product_history import (
    ProductHistoryCapability,
    ProductHistoryResult,
)


def create_capability() -> ProductHistoryCapability:
    return ProductHistoryCapability(InMemoryProductHistoryRepository())


def test_get_product_history_returns_p4711() -> None:
    result = create_capability().get_product_history("P4711")

    assert isinstance(result, ProductHistoryResult)
    assert result.found is True
    assert result.product_id == "P4711"
    assert len(result.steps) == 3
    assert result.steps[-1].station_id == "S04"
    assert result.steps[-1].status is ProductionStepStatus.FAILED
    assert result.steps[-1].error_code == "E-STOP-17"


def test_get_product_history_returns_structured_not_found_result() -> None:
    result = create_capability().get_product_history("P9999")

    assert isinstance(result, ProductHistoryResult)
    assert result.found is False
    assert result.product_id == "P9999"
    assert result.steps == ()


@pytest.mark.parametrize("value", ("P47", "4711", "P47A1", ""))
def test_product_id_rejects_invalid_domain_format(value: str) -> None:
    with pytest.raises(ValueError, match="invalid format|must not be empty"):
        ProductId(value)


@pytest.mark.parametrize("value", ("S4", "04", "S0A", ""))
def test_station_id_rejects_invalid_domain_format(value: str) -> None:
    with pytest.raises(ValueError, match="invalid format|must not be empty"):
        StationId(value)


def test_get_product_history_preserves_production_step_order() -> None:
    result = create_capability().get_product_history("P4711")

    timestamps = [step.timestamp for step in result.steps]
    assert timestamps == sorted(timestamps)
    assert [step.station_id for step in result.steps] == ["S01", "S02", "S04"]


def test_product_history_rejects_naive_timestamp() -> None:
    step = ProductionStep(
        station_id=StationId("S01"),
        timestamp=datetime(2026, 1, 15, 8, 0),  # noqa: DTZ001
        status=ProductionStepStatus.COMPLETED,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        ProductHistory(product_id=ProductId("P1000"), steps=(step,))


def test_product_history_rejects_unsorted_steps() -> None:
    later_step = ProductionStep(
        station_id=StationId("S02"),
        timestamp=datetime(2026, 1, 15, 8, 5, tzinfo=UTC),
        status=ProductionStepStatus.COMPLETED,
    )
    earlier_step = ProductionStep(
        station_id=StationId("S01"),
        timestamp=datetime(2026, 1, 15, 8, 0, tzinfo=UTC),
        status=ProductionStepStatus.COMPLETED,
    )

    with pytest.raises(ValueError, match="ordered chronologically"):
        ProductHistory(
            product_id=ProductId("P1000"),
            steps=(later_step, earlier_step),
        )


def test_product_history_accepts_ordered_timezone_aware_steps() -> None:
    first_step = ProductionStep(
        station_id=StationId("S01"),
        timestamp=datetime(2026, 1, 15, 8, 0, tzinfo=UTC),
        status=ProductionStepStatus.COMPLETED,
    )
    second_step = ProductionStep(
        station_id=StationId("S02"),
        timestamp=datetime(2026, 1, 15, 8, 5, tzinfo=UTC),
        status=ProductionStepStatus.FAILED,
        error_code="E-STOP-17",
    )

    history = ProductHistory(
        product_id=ProductId("P1000"),
        steps=(first_step, second_step),
    )

    assert history.steps == (first_step, second_step)
