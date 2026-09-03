from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise


@dataclass(frozen=True, slots=True)
class ProductId:
    value: str

    def __post_init__(self) -> None:
        normalized_value = self.value.strip()
        if not normalized_value:
            raise ValueError("Product ID must not be empty")
        object.__setattr__(self, "value", normalized_value)


@dataclass(frozen=True, slots=True)
class StationId:
    value: str

    def __post_init__(self) -> None:
        normalized_value = self.value.strip()
        if not normalized_value:
            raise ValueError("Station ID must not be empty")
        object.__setattr__(self, "value", normalized_value)


class ProductionStepStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ProductionStep:
    station_id: StationId
    timestamp: datetime
    status: ProductionStepStatus
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProductHistory:
    product_id: ProductId
    steps: tuple[ProductionStep, ...]

    def __post_init__(self) -> None:
        normalized_steps = tuple(self.steps)
        object.__setattr__(self, "steps", normalized_steps)

        if any(step.timestamp.utcoffset() is None for step in normalized_steps):
            raise ValueError("Production step timestamps must be timezone-aware")

        if any(
            current.timestamp > following.timestamp
            for current, following in pairwise(normalized_steps)
        ):
            raise ValueError("Production steps must be ordered chronologically")
