from collections.abc import Iterable
from datetime import UTC, datetime

from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    ProductionStep,
    ProductionStepStatus,
    StationId,
)


class InMemoryProductHistoryRepository:
    def __init__(self, histories: Iterable[ProductHistory] | None = None) -> None:
        source = histories if histories is not None else _create_demo_histories()
        self._histories = {history.product_id: history for history in source}

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        return self._histories.get(product_id)


def _create_demo_histories() -> tuple[ProductHistory, ...]:
    return (
        ProductHistory(
            product_id=ProductId("P4711"),
            steps=(
                ProductionStep(
                    station_id=StationId("S01"),
                    timestamp=datetime(2026, 1, 15, 8, 0, tzinfo=UTC),
                    status=ProductionStepStatus.COMPLETED,
                ),
                ProductionStep(
                    station_id=StationId("S02"),
                    timestamp=datetime(2026, 1, 15, 8, 4, tzinfo=UTC),
                    status=ProductionStepStatus.COMPLETED,
                ),
                ProductionStep(
                    station_id=StationId("S04"),
                    timestamp=datetime(2026, 1, 15, 8, 9, tzinfo=UTC),
                    status=ProductionStepStatus.FAILED,
                    error_code="E-STOP-17",
                ),
            ),
        ),
    )
