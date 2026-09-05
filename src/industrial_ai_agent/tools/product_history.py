from datetime import datetime

from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.domain.product_history import (
    ProductId,
    ProductionStepStatus,
)
from industrial_ai_agent.domain.product_history_repository import (
    ProductHistoryRepository,
)
from industrial_ai_agent.domain.security import DataClassification


class ProductionStepResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    station_id: str
    timestamp: datetime
    status: ProductionStepStatus
    error_code: str | None = None


class ProductHistoryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str
    found: bool
    steps: tuple[ProductionStepResult, ...]
    classification: DataClassification = DataClassification.CONFIDENTIAL


class ProductHistoryCapability:
    def __init__(self, repository: ProductHistoryRepository) -> None:
        self._repository = repository

    def get_product_history(self, product_id: str) -> ProductHistoryResult:
        requested_product_id = ProductId(product_id)
        history = self._repository.get_product_history(requested_product_id)

        if history is None:
            return ProductHistoryResult(
                product_id=requested_product_id.value,
                found=False,
                steps=(),
            )

        return ProductHistoryResult(
            product_id=history.product_id.value,
            found=True,
            classification=history.classification,
            steps=tuple(
                ProductionStepResult(
                    station_id=step.station_id.value,
                    timestamp=step.timestamp,
                    status=step.status,
                    error_code=step.error_code,
                )
                for step in history.steps
            ),
        )
