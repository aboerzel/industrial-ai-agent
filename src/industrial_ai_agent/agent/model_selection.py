"""Provider-independent model assignment, capability, and execution decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from time import perf_counter
from typing import NoReturn, Protocol
from uuid import UUID

from industrial_ai_agent.agent.llm import ModelId
from industrial_ai_agent.agent.model_egress import (
    ExecutionZone,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.domain.security import DataClassification

_CONSUMER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class ModelCapability(StrEnum):
    TEXT = "text"
    TOOL_CALLING = "tool_calling"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    EMBEDDING = "embedding"
    OBJECT_DETECTION = "object_detection"
    SEGMENTATION = "segmentation"


class QualityClass(StrEnum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class CostClass(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class ModelConsumerId:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not _CONSUMER_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid model consumer ID")
        object.__setattr__(self, "value", normalized)


AGENT_CONSUMER = ModelConsumerId("agent")
RCA_REASONING_CONSUMER = ModelConsumerId("rca.reasoning")


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    model_id: ModelId
    display_name: str
    provider: str
    provider_model: str
    execution_zone: ExecutionZone
    max_data_classification: DataClassification
    capabilities: frozenset[ModelCapability]
    quality_class: QualityClass
    cost_class: CostClass


@dataclass(frozen=True, slots=True)
class ModelConsumerDefinition:
    """Presentation-safe description of one configured model consumer."""

    consumer_id: ModelConsumerId
    display_name: str
    required_capabilities: frozenset[ModelCapability]


@dataclass(frozen=True, slots=True)
class ModelAssignment:
    consumer_id: ModelConsumerId
    data_classification: DataClassification
    model_id: ModelId
    updated_at: datetime | None = None
    updated_by: str | None = None


class ModelAssignmentRepository(Protocol):
    def get(
        self,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
    ) -> ModelAssignment | None: ...

    def list(self) -> tuple[ModelAssignment, ...]: ...

    def upsert(self, assignment: ModelAssignment) -> ModelAssignment: ...


class ModelCatalog(Protocol):
    def get_model(self, model_id: str) -> ModelDefinition: ...

    def list_models(self) -> tuple[ModelDefinition, ...]: ...


class ModelDecisionOutcome(StrEnum):
    EXECUTION_ALLOWED = "EXECUTION_ALLOWED"
    EXECUTED = "EXECUTED"
    EGRESS_DENIED = "EGRESS_DENIED"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    MODEL_NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"


@dataclass(frozen=True, slots=True)
class ModelDecision:
    consumer_id: ModelConsumerId
    effective_data_classification: DataClassification
    required_capabilities: frozenset[ModelCapability]
    outcome: ModelDecisionOutcome
    model: ModelDefinition | None = None
    capability_allowed: bool | None = None
    egress_allowed: bool | None = None
    run_id: UUID | None = None
    error_code: str | None = None
    duration_ms: float | None = None


class ModelDecisionObserver(Protocol):
    def record(self, decision: ModelDecision) -> None: ...


class ModelResolutionError(RuntimeError):
    def __init__(self, decision: ModelDecision) -> None:
        self.decision = decision
        self.code = decision.error_code or decision.outcome.value.lower()
        super().__init__(self.code)


class ModelResolutionService:
    """Resolve exactly one configured model and deny without fallback."""

    def __init__(
        self,
        *,
        catalog: ModelCatalog,
        assignments: ModelAssignmentRepository,
        authorizer: ModelExecutionAuthorizer,
        consumer_requirements: dict[ModelConsumerId, frozenset[ModelCapability]],
        observer: ModelDecisionObserver | None = None,
    ) -> None:
        self._catalog = catalog
        self._assignments = assignments
        self._authorizer = authorizer
        self._requirements = dict(consumer_requirements)
        self._observer = observer

    @property
    def supported_consumers(self) -> tuple[ModelConsumerId, ...]:
        return tuple(sorted(self._requirements, key=lambda item: item.value))

    def required_capabilities(
        self, consumer_id: ModelConsumerId
    ) -> frozenset[ModelCapability]:
        try:
            return self._requirements[consumer_id]
        except KeyError as error:
            raise ValueError("Unsupported model consumer") from error

    def resolve_model(
        self,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
        *,
        run_id: UUID | None = None,
    ) -> ModelDecision:
        started = perf_counter()
        required = self.required_capabilities(consumer_id)
        assignment = self._assignments.get(consumer_id, data_classification)
        if assignment is None:
            return self._deny(
                ModelDecision(
                    consumer_id=consumer_id,
                    effective_data_classification=data_classification,
                    required_capabilities=required,
                    outcome=ModelDecisionOutcome.MODEL_NOT_CONFIGURED,
                    run_id=run_id,
                    error_code="model_not_configured",
                    duration_ms=_duration_ms(started),
                )
            )
        try:
            model = self._catalog.get_model(assignment.model_id.value)
        except ValueError:
            return self._deny(
                ModelDecision(
                    consumer_id=consumer_id,
                    effective_data_classification=data_classification,
                    required_capabilities=required,
                    outcome=ModelDecisionOutcome.MODEL_NOT_CONFIGURED,
                    run_id=run_id,
                    error_code="model_not_configured",
                    duration_ms=_duration_ms(started),
                )
            )
        capability_allowed = required <= model.capabilities
        egress_allowed = self._authorizer.is_allowed(
            data_classification,
            model.execution_zone,
            model.max_data_classification,
        )
        if not egress_allowed:
            return self._deny(
                ModelDecision(
                    consumer_id=consumer_id,
                    effective_data_classification=data_classification,
                    required_capabilities=required,
                    outcome=ModelDecisionOutcome.EGRESS_DENIED,
                    model=model,
                    capability_allowed=capability_allowed,
                    egress_allowed=False,
                    run_id=run_id,
                    error_code="model_egress_denied",
                    duration_ms=_duration_ms(started),
                )
            )
        if not capability_allowed:
            return self._deny(
                ModelDecision(
                    consumer_id=consumer_id,
                    effective_data_classification=data_classification,
                    required_capabilities=required,
                    outcome=ModelDecisionOutcome.CAPABILITY_MISMATCH,
                    model=model,
                    capability_allowed=False,
                    egress_allowed=True,
                    run_id=run_id,
                    error_code="model_capability_mismatch",
                    duration_ms=_duration_ms(started),
                )
            )
        decision = ModelDecision(
            consumer_id=consumer_id,
            effective_data_classification=data_classification,
            required_capabilities=required,
            outcome=ModelDecisionOutcome.EXECUTION_ALLOWED,
            model=model,
            capability_allowed=True,
            egress_allowed=True,
            run_id=run_id,
            duration_ms=_duration_ms(started),
        )
        self._record(decision)
        return decision

    def _deny(self, decision: ModelDecision) -> NoReturn:
        self._record(decision)
        raise ModelResolutionError(decision)

    def _record(self, decision: ModelDecision) -> None:
        if self._observer is not None:
            self._observer.record(decision)


AGENT_REQUIREMENTS = frozenset(
    {
        ModelCapability.TEXT,
        ModelCapability.TOOL_CALLING,
        ModelCapability.STRUCTURED_OUTPUT,
    }
)

RCA_REASONING_REQUIREMENTS = frozenset(
    {ModelCapability.TEXT, ModelCapability.STRUCTURED_OUTPUT}
)

CURRENT_MODEL_CONSUMERS = (
    ModelConsumerDefinition(AGENT_CONSUMER, "Agent", AGENT_REQUIREMENTS),
    ModelConsumerDefinition(
        RCA_REASONING_CONSUMER, "Root Cause Analysis", RCA_REASONING_REQUIREMENTS
    ),
)

CURRENT_CONSUMER_REQUIREMENTS = {
    consumer.consumer_id: consumer.required_capabilities
    for consumer in CURRENT_MODEL_CONSUMERS
}


def _duration_ms(started: float) -> float:
    return (perf_counter() - started) * 1000
