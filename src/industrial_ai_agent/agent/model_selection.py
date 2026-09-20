"""Provider-independent model assignment, capability, and execution decisions."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from time import perf_counter
from typing import NoReturn, Protocol
from uuid import UUID

from industrial_ai_agent.agent.llm import LLMClient, LLMRequest, LLMResponse, ModelId
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


class ModelCallType(StrEnum):
    """Stable labels for the capabilities needed by one provider invocation."""

    PLAIN_TEXT = "plain_text"
    TOOL_DECISION = "tool_decision"
    STRUCTURED_RESPONSE = "structured_response"
    TOOL_DECISION_STRUCTURED = "tool_decision_structured"
    RCA_REASONING = "rca_reasoning"


class QualityClass(StrEnum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class CostClass(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"


class ModelSelectionMode(StrEnum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class ModelSelectionPolicy(StrEnum):
    QUALITY_FIRST = "QUALITY_FIRST"
    COST_FIRST = "COST_FIRST"


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
    incompatible_capability_combinations: frozenset[frozenset[ModelCapability]] = (
        frozenset()
    )


@dataclass(frozen=True, slots=True)
class ModelConsumerDefinition:
    """Presentation-safe description of one configured model consumer."""

    consumer_id: ModelConsumerId
    display_name: str
    required_capabilities: frozenset[ModelCapability]
    call_requirements: tuple[ModelCallRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelCallRequirement:
    """Capabilities required together by one concrete model invocation."""

    call_type: ModelCallType
    capabilities: frozenset[ModelCapability]


@dataclass(frozen=True, slots=True)
class CapabilityValidation:
    allowed: bool
    missing_capabilities: frozenset[ModelCapability] = frozenset()
    incompatible_combination: frozenset[ModelCapability] | None = None
    call_type: ModelCallType | None = None


@dataclass(frozen=True, slots=True)
class ModelAssignment:
    consumer_id: ModelConsumerId
    data_classification: DataClassification
    model_id: ModelId | None
    selection_mode: ModelSelectionMode = ModelSelectionMode.MANUAL
    selection_policy: ModelSelectionPolicy | None = None
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
    missing_capabilities: frozenset[ModelCapability] = frozenset()
    incompatible_capability_combination: frozenset[ModelCapability] | None = None
    call_type: ModelCallType | None = None
    egress_allowed: bool | None = None
    run_id: UUID | None = None
    error_code: str | None = None
    duration_ms: float | None = None
    selection_mode: ModelSelectionMode = ModelSelectionMode.MANUAL
    selection_policy: ModelSelectionPolicy | None = None
    candidates: tuple[ModelSelectionCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelSelectionCandidate:
    """Metadata-only explanation for one automatic-selection catalog candidate."""

    model: ModelDefinition
    capability_allowed: bool
    egress_allowed: bool | None
    exclusion_reason: str | None = None
    runtime_available: bool = True
    missing_capabilities: frozenset[ModelCapability] = frozenset()
    incompatible_capability_combination: frozenset[ModelCapability] | None = None
    call_type: ModelCallType | None = None


class CapabilityCheckedLLMClient:
    """Final per-request capability guard before the egress/provider boundary."""

    def __init__(
        self,
        delegate: LLMClient,
        catalog: ModelCatalog,
        *,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
    ) -> None:
        self._delegate = delegate
        self._catalog = catalog
        self._consumer_id = consumer_id
        self._data_classification = data_classification

    def chat(self, model_id: ModelId, request: LLMRequest) -> LLMResponse:
        model = self._catalog.get_model(model_id.value)
        requirement = call_requirement_for_request(request)
        validation = validate_model_capabilities(model, (requirement,))
        if not validation.allowed:
            raise ModelResolutionError(
                ModelDecision(
                    consumer_id=self._consumer_id,
                    effective_data_classification=self._data_classification,
                    required_capabilities=requirement.capabilities,
                    outcome=ModelDecisionOutcome.CAPABILITY_MISMATCH,
                    model=model,
                    capability_allowed=False,
                    missing_capabilities=validation.missing_capabilities,
                    incompatible_capability_combination=(
                        validation.incompatible_combination
                    ),
                    call_type=requirement.call_type,
                    error_code="model_capability_mismatch",
                )
            )
        return self._delegate.chat(model_id, request)

    def raise_request_classification(self, classification: DataClassification) -> None:
        self._data_classification = max(self._data_classification, classification)
        raise_classification = getattr(
            self._delegate, "raise_request_classification", None
        )
        if callable(raise_classification):
            raise_classification(classification)


class ModelDecisionObserver(Protocol):
    def record(self, decision: ModelDecision) -> None: ...


class ModelResolutionError(RuntimeError):
    def __init__(self, decision: ModelDecision) -> None:
        self.decision = decision
        self.code = decision.error_code or decision.outcome.value.lower()
        super().__init__(self.code)


def call_requirement_for_request(request: LLMRequest) -> ModelCallRequirement:
    """Derive the simultaneous capability set from one provider request."""
    capabilities = {ModelCapability.TEXT}
    if request.tools:
        capabilities.add(ModelCapability.TOOL_CALLING)
    if request.response_format is not None:
        capabilities.add(ModelCapability.STRUCTURED_OUTPUT)
    if request.tools and request.response_format is not None:
        call_type = ModelCallType.TOOL_DECISION_STRUCTURED
    elif request.tools:
        call_type = ModelCallType.TOOL_DECISION
    elif request.response_format is not None:
        call_type = ModelCallType.STRUCTURED_RESPONSE
    else:
        call_type = ModelCallType.PLAIN_TEXT
    return ModelCallRequirement(call_type, frozenset(capabilities))


def validate_model_capabilities(
    model: ModelDefinition,
    requirements: tuple[ModelCallRequirement, ...],
) -> CapabilityValidation:
    """Validate each invocation independently; workflow capability unions are not calls."""
    for requirement in requirements:
        missing = requirement.capabilities - model.capabilities
        if missing:
            return CapabilityValidation(
                allowed=False,
                missing_capabilities=missing,
                call_type=requirement.call_type,
            )
        incompatible = next(
            (
                combination
                for combination in model.incompatible_capability_combinations
                if combination <= requirement.capabilities
            ),
            None,
        )
        if incompatible is not None:
            return CapabilityValidation(
                allowed=False,
                incompatible_combination=incompatible,
                call_type=requirement.call_type,
            )
    return CapabilityValidation(allowed=True)


def _normalize_call_requirements(
    requirements: frozenset[ModelCapability] | tuple[ModelCallRequirement, ...],
) -> tuple[ModelCallRequirement, ...]:
    if isinstance(requirements, frozenset):
        return (ModelCallRequirement(ModelCallType.PLAIN_TEXT, requirements),)
    return requirements


def _workflow_capabilities(
    requirements: tuple[ModelCallRequirement, ...],
) -> frozenset[ModelCapability]:
    return frozenset(
        capability
        for requirement in requirements
        for capability in requirement.capabilities
    )


class ModelResolutionService:
    """Resolve exactly one configured model and deny without fallback."""

    def __init__(
        self,
        *,
        catalog: ModelCatalog,
        assignments: ModelAssignmentRepository,
        authorizer: ModelExecutionAuthorizer,
        consumer_requirements: dict[
            ModelConsumerId,
            frozenset[ModelCapability] | tuple[ModelCallRequirement, ...],
        ],
        observer: ModelDecisionObserver | None = None,
        model_is_statically_available: Callable[[ModelDefinition], bool] | None = None,
    ) -> None:
        self._catalog = catalog
        self._assignments = assignments
        self._authorizer = authorizer
        self._requirements = {
            consumer_id: _normalize_call_requirements(requirements)
            for consumer_id, requirements in consumer_requirements.items()
        }
        self._observer = observer
        self._model_is_statically_available = (
            model_is_statically_available or _always_statically_available
        )

    @property
    def supported_consumers(self) -> tuple[ModelConsumerId, ...]:
        return tuple(sorted(self._requirements, key=lambda item: item.value))

    def required_capabilities(
        self, consumer_id: ModelConsumerId
    ) -> frozenset[ModelCapability]:
        try:
            return _workflow_capabilities(self._requirements[consumer_id])
        except KeyError as error:
            raise ValueError("Unsupported model consumer") from error

    def call_requirements(
        self, consumer_id: ModelConsumerId
    ) -> tuple[ModelCallRequirement, ...]:
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
        call_requirements = self.call_requirements(consumer_id)
        assignment = self._assignments.get(consumer_id, data_classification)
        if assignment is None:
            return self._not_configured(
                consumer_id, data_classification, required, run_id, started
            )
        if assignment.selection_mode is ModelSelectionMode.AUTO:
            return self._resolve_auto(
                consumer_id=consumer_id,
                data_classification=data_classification,
                required=required,
                call_requirements=call_requirements,
                assignment=assignment,
                run_id=run_id,
                started=started,
            )
        if (
            assignment.selection_mode is not ModelSelectionMode.MANUAL
            or assignment.model_id is None
        ):
            return self._not_configured(
                consumer_id, data_classification, required, run_id, started
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
                    selection_mode=ModelSelectionMode.MANUAL,
                )
            )
        capability_validation = validate_model_capabilities(model, call_requirements)
        capability_allowed = capability_validation.allowed
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
                    missing_capabilities=capability_validation.missing_capabilities,
                    incompatible_capability_combination=(
                        capability_validation.incompatible_combination
                    ),
                    call_type=capability_validation.call_type,
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
                    missing_capabilities=capability_validation.missing_capabilities,
                    incompatible_capability_combination=(
                        capability_validation.incompatible_combination
                    ),
                    call_type=capability_validation.call_type,
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
            selection_mode=ModelSelectionMode.MANUAL,
        )
        self._record(decision)
        return decision

    def _resolve_auto(
        self,
        *,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
        required: frozenset[ModelCapability],
        call_requirements: tuple[ModelCallRequirement, ...],
        assignment: ModelAssignment,
        run_id: UUID | None,
        started: float,
    ) -> ModelDecision:
        policy = assignment.selection_policy
        if policy is None:
            return self._not_configured(
                consumer_id,
                data_classification,
                required,
                run_id,
                started,
                selection_mode=ModelSelectionMode.AUTO,
            )
        candidates: list[ModelSelectionCandidate] = []
        statically_available: list[ModelDefinition] = []
        for model in self._catalog.list_models():
            if not self._model_is_statically_available(model):
                candidates.append(
                    ModelSelectionCandidate(
                        model, False, None, "runtime_unavailable", False
                    )
                )
                continue
            statically_available.append(model)
        capable: list[ModelDefinition] = []
        for model in statically_available:
            capability_validation = validate_model_capabilities(
                model, call_requirements
            )
            if not capability_validation.allowed:
                candidates.append(
                    ModelSelectionCandidate(
                        model,
                        False,
                        None,
                        "capability_mismatch",
                        missing_capabilities=capability_validation.missing_capabilities,
                        incompatible_capability_combination=(
                            capability_validation.incompatible_combination
                        ),
                        call_type=capability_validation.call_type,
                    )
                )
                continue
            capable.append(model)
        if not capable:
            if not statically_available:
                return self._not_configured(
                    consumer_id,
                    data_classification,
                    required,
                    run_id,
                    started,
                    selection_mode=ModelSelectionMode.AUTO,
                    selection_policy=policy,
                    candidates=tuple(candidates),
                    error_code="model_runtime_unavailable",
                )
            return self._deny(
                ModelDecision(
                    consumer_id=consumer_id,
                    effective_data_classification=data_classification,
                    required_capabilities=required,
                    outcome=ModelDecisionOutcome.CAPABILITY_MISMATCH,
                    capability_allowed=False,
                    missing_capabilities=capability_validation.missing_capabilities,
                    incompatible_capability_combination=(
                        capability_validation.incompatible_combination
                    ),
                    call_type=capability_validation.call_type,
                    egress_allowed=None,
                    run_id=run_id,
                    error_code="model_capability_mismatch",
                    duration_ms=_duration_ms(started),
                    selection_mode=ModelSelectionMode.AUTO,
                    selection_policy=policy,
                    candidates=tuple(candidates),
                )
            )
        authorized: list[ModelDefinition] = []
        for model in capable:
            egress_allowed = self._authorizer.is_allowed(
                data_classification,
                model.execution_zone,
                model.max_data_classification,
            )
            candidates.append(
                ModelSelectionCandidate(
                    model,
                    True,
                    egress_allowed,
                    None if egress_allowed else "egress_denied",
                )
            )
            if egress_allowed:
                authorized.append(model)
        if not authorized:
            return self._deny(
                ModelDecision(
                    consumer_id=consumer_id,
                    effective_data_classification=data_classification,
                    required_capabilities=required,
                    outcome=ModelDecisionOutcome.EGRESS_DENIED,
                    capability_allowed=True,
                    egress_allowed=False,
                    run_id=run_id,
                    error_code="model_egress_denied",
                    duration_ms=_duration_ms(started),
                    selection_mode=ModelSelectionMode.AUTO,
                    selection_policy=policy,
                    candidates=tuple(candidates),
                )
            )
        model = min(authorized, key=lambda item: _selection_sort_key(item, policy))
        # Revalidate the chosen candidate. Filtering never substitutes for final guards.
        capability_validation = validate_model_capabilities(model, call_requirements)
        capability_allowed = capability_validation.allowed
        egress_allowed = self._authorizer.is_allowed(
            data_classification, model.execution_zone, model.max_data_classification
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
                    missing_capabilities=capability_validation.missing_capabilities,
                    incompatible_capability_combination=(
                        capability_validation.incompatible_combination
                    ),
                    call_type=capability_validation.call_type,
                    egress_allowed=False,
                    run_id=run_id,
                    error_code="model_egress_denied",
                    duration_ms=_duration_ms(started),
                    selection_mode=ModelSelectionMode.AUTO,
                    selection_policy=policy,
                    candidates=tuple(candidates),
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
                    missing_capabilities=capability_validation.missing_capabilities,
                    incompatible_capability_combination=(
                        capability_validation.incompatible_combination
                    ),
                    call_type=capability_validation.call_type,
                    egress_allowed=True,
                    run_id=run_id,
                    error_code="model_capability_mismatch",
                    duration_ms=_duration_ms(started),
                    selection_mode=ModelSelectionMode.AUTO,
                    selection_policy=policy,
                    candidates=tuple(candidates),
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
            selection_mode=ModelSelectionMode.AUTO,
            selection_policy=policy,
            candidates=tuple(candidates),
        )
        self._record(decision)
        return decision

    def _not_configured(
        self,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
        required: frozenset[ModelCapability],
        run_id: UUID | None,
        started: float,
        *,
        selection_mode: ModelSelectionMode = ModelSelectionMode.MANUAL,
        selection_policy: ModelSelectionPolicy | None = None,
        candidates: tuple[ModelSelectionCandidate, ...] = (),
        error_code: str = "model_not_configured",
    ) -> NoReturn:
        return self._deny(
            ModelDecision(
                consumer_id=consumer_id,
                effective_data_classification=data_classification,
                required_capabilities=required,
                outcome=ModelDecisionOutcome.MODEL_NOT_CONFIGURED,
                run_id=run_id,
                error_code=error_code,
                duration_ms=_duration_ms(started),
                selection_mode=selection_mode,
                selection_policy=selection_policy,
                candidates=candidates,
            )
        )

    def _deny(self, decision: ModelDecision) -> NoReturn:
        self._record(decision)
        raise ModelResolutionError(decision)

    def _record(self, decision: ModelDecision) -> None:
        if self._observer is not None:
            self._observer.record(decision)


AGENT_CALL_REQUIREMENTS = (
    ModelCallRequirement(
        ModelCallType.TOOL_DECISION,
        frozenset({ModelCapability.TEXT, ModelCapability.TOOL_CALLING}),
    ),
    ModelCallRequirement(
        ModelCallType.STRUCTURED_RESPONSE,
        frozenset({ModelCapability.TEXT, ModelCapability.STRUCTURED_OUTPUT}),
    ),
    ModelCallRequirement(ModelCallType.PLAIN_TEXT, frozenset({ModelCapability.TEXT})),
)
RCA_REASONING_CALL_REQUIREMENTS = (
    ModelCallRequirement(
        ModelCallType.RCA_REASONING,
        frozenset({ModelCapability.TEXT, ModelCapability.STRUCTURED_OUTPUT}),
    ),
)
AGENT_REQUIREMENTS = _workflow_capabilities(AGENT_CALL_REQUIREMENTS)
RCA_REASONING_REQUIREMENTS = _workflow_capabilities(RCA_REASONING_CALL_REQUIREMENTS)

CURRENT_MODEL_CONSUMERS = (
    ModelConsumerDefinition(
        AGENT_CONSUMER, "Agent", AGENT_REQUIREMENTS, AGENT_CALL_REQUIREMENTS
    ),
    ModelConsumerDefinition(
        RCA_REASONING_CONSUMER,
        "Root Cause Analysis",
        RCA_REASONING_REQUIREMENTS,
        RCA_REASONING_CALL_REQUIREMENTS,
    ),
)

CURRENT_CONSUMER_REQUIREMENTS = {
    consumer.consumer_id: consumer.call_requirements
    for consumer in CURRENT_MODEL_CONSUMERS
}


def _duration_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _always_statically_available(_: ModelDefinition) -> bool:
    """Keep non-runtime catalog implementations usable in deterministic unit tests."""

    return True


def _selection_sort_key(
    model: ModelDefinition, policy: ModelSelectionPolicy
) -> tuple[int, int, str]:
    quality_rank = {QualityClass.HIGH: 0, QualityClass.STANDARD: 1}
    cost_rank = {CostClass.LOW: 0, CostClass.HIGH: 1}
    if policy is ModelSelectionPolicy.QUALITY_FIRST:
        return (
            quality_rank[model.quality_class],
            cost_rank[model.cost_class],
            model.model_id.value,
        )
    return (
        cost_rank[model.cost_class],
        quality_rank[model.quality_class],
        model.model_id.value,
    )
