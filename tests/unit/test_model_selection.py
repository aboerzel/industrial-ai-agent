from contextlib import contextmanager
from uuid import UUID

import pytest

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ModelId,
)
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressDeniedError,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import (
    CostClass,
    ModelAssignment,
    ModelCapability,
    ModelConsumerId,
    ModelDecision,
    ModelDecisionOutcome,
    ModelDefinition,
    ModelResolutionError,
    ModelResolutionService,
    QualityClass,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.model_decision_observer import (
    TelemetryModelDecisionObserver,
)

VISION_VLM = ModelConsumerId("vision.vlm")
VISION_REQUIREMENTS = frozenset({ModelCapability.TEXT, ModelCapability.VISION})


class Catalog:
    def __init__(self, *models: ModelDefinition) -> None:
        self.models = {model.model_id.value: model for model in models}

    def get_model(self, model_id: str) -> ModelDefinition:
        try:
            return self.models[model_id]
        except KeyError as error:
            raise ValueError("Unknown model ID") from error

    def list_models(self) -> tuple[ModelDefinition, ...]:
        return tuple(self.models.values())


class Assignments:
    def __init__(self, *assignments: ModelAssignment) -> None:
        self.assignments = {
            (item.consumer_id, item.data_classification): item for item in assignments
        }

    def get(self, consumer_id, data_classification):
        return self.assignments.get((consumer_id, data_classification))

    def list(self):
        return tuple(self.assignments.values())

    def upsert(self, assignment):
        self.assignments[(assignment.consumer_id, assignment.data_classification)] = (
            assignment
        )
        return assignment


def _model(
    model_id: str,
    *,
    zone: ExecutionZone,
    capabilities: frozenset[ModelCapability] = VISION_REQUIREMENTS,
) -> ModelDefinition:
    return ModelDefinition(
        model_id=ModelId(model_id),
        display_name=model_id.replace("_", " ").title(),
        provider="test",
        provider_model=f"test/{model_id}",
        execution_zone=zone,
        max_data_classification=(
            DataClassification.RESTRICTED
            if zone is ExecutionZone.LOCAL
            else DataClassification.CONFIDENTIAL
        ),
        capabilities=capabilities,
        quality_class=QualityClass.STANDARD,
        cost_class=CostClass.LOW,
    )


def _resolver(model: ModelDefinition) -> ModelResolutionService:
    assignment = ModelAssignment(
        consumer_id=VISION_VLM,
        data_classification=DataClassification.RESTRICTED,
        model_id=model.model_id,
    )
    return ModelResolutionService(
        catalog=Catalog(model),
        assignments=Assignments(assignment),
        authorizer=ModelExecutionAuthorizer(),
        consumer_requirements={VISION_VLM: VISION_REQUIREMENTS},
    )


def test_restricted_vision_allows_suitable_local_model() -> None:
    decision = _resolver(
        _model("local_vision", zone=ExecutionZone.LOCAL)
    ).resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert decision.outcome is ModelDecisionOutcome.EXECUTION_ALLOWED
    assert decision.capability_allowed is True
    assert decision.egress_allowed is True


def test_restricted_vision_denies_technically_suitable_public_model() -> None:
    resolver = _resolver(_model("public_vision", zone=ExecutionZone.PUBLIC_CLOUD))

    with pytest.raises(ModelResolutionError) as captured:
        resolver.resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert captured.value.decision.outcome is ModelDecisionOutcome.EGRESS_DENIED
    assert captured.value.decision.capability_allowed is True
    assert captured.value.decision.egress_allowed is False


def test_restricted_vision_denies_allowed_but_unsuitable_local_model() -> None:
    resolver = _resolver(
        _model(
            "local_text",
            zone=ExecutionZone.LOCAL,
            capabilities=frozenset({ModelCapability.TEXT}),
        )
    )

    with pytest.raises(ModelResolutionError) as captured:
        resolver.resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert captured.value.decision.outcome is ModelDecisionOutcome.CAPABILITY_MISMATCH
    assert captured.value.decision.capability_allowed is False
    assert captured.value.decision.egress_allowed is True


def test_missing_assignment_fails_closed_without_catalog_fallback() -> None:
    resolver = ModelResolutionService(
        catalog=Catalog(_model("available", zone=ExecutionZone.LOCAL)),
        assignments=Assignments(),
        authorizer=ModelExecutionAuthorizer(),
        consumer_requirements={VISION_VLM: VISION_REQUIREMENTS},
    )

    with pytest.raises(ModelResolutionError) as captured:
        resolver.resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert captured.value.decision.outcome is ModelDecisionOutcome.MODEL_NOT_CONFIGURED
    assert captured.value.decision.model is None


class PublicZoneCatalog:
    def get_execution_zone(self, model_id: str) -> ExecutionZone:
        assert model_id == "public_vision"
        return ExecutionZone.PUBLIC_CLOUD

    def get_max_data_classification(self, model_id: str) -> DataClassification:
        assert model_id == "public_vision"
        return DataClassification.CONFIDENTIAL


class CapturingClient:
    called = False

    def chat(self, model_id, request):
        self.called = True
        return LLMResponse(text="unsafe", finish_reason=FinishReason.STOP)


def test_final_provider_guard_blocks_restricted_public_invocation() -> None:
    delegate = CapturingClient()
    checked = EgressCheckedLLMClient(
        delegate,
        PublicZoneCatalog(),
        DataClassification.RESTRICTED,
    )

    with pytest.raises(ModelEgressDeniedError):
        checked.chat(
            ModelId("public_vision"),
            LLMRequest(
                messages=(LLMMessage(role=MessageRole.USER, content="protected"),)
            ),
        )

    assert delegate.called is False


def test_lower_tool_classification_cannot_lower_restricted_provider_context() -> None:
    delegate = CapturingClient()
    checked = EgressCheckedLLMClient(
        delegate,
        PublicZoneCatalog(),
        DataClassification.RESTRICTED,
    )

    checked.raise_request_classification(DataClassification.PUBLIC)

    with pytest.raises(ModelEgressDeniedError):
        checked.chat(
            ModelId("public_vision"),
            LLMRequest(
                messages=(LLMMessage(role=MessageRole.USER, content="derived"),)
            ),
        )
    assert delegate.called is False


def test_model_decision_telemetry_exposes_distinct_bounded_outcome_metadata() -> None:
    telemetry = CapturingTelemetry()
    observer = TelemetryModelDecisionObserver(telemetry)  # type: ignore[arg-type]
    run_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    model = _model("public_vision", zone=ExecutionZone.PUBLIC_CLOUD)

    observer.record(
        ModelDecision(
            consumer_id=VISION_VLM,
            effective_data_classification=DataClassification.RESTRICTED,
            required_capabilities=VISION_REQUIREMENTS,
            outcome=ModelDecisionOutcome.EGRESS_DENIED,
            model=model,
            capability_allowed=True,
            egress_allowed=False,
            run_id=run_id,
            error_code="model_egress_denied",
            duration_ms=1.25,
        )
    )

    assert telemetry.name == "model.decision"
    assert telemetry.attributes == {
        "model.consumer_id": "vision.vlm",
        "data.classification": "RESTRICTED",
        "model.required_capabilities": "text,vision",
        "model.capability_decision": "ALLOW",
        "model.egress_decision": "DENY",
        "model.decision_outcome": "EGRESS_DENIED",
        "run.id": str(run_id),
        "error.code": "model_egress_denied",
        "operation.duration_ms": 1.25,
        "model.id": "public_vision",
        "model.provider": "test",
        "execution.zone": "PUBLIC_CLOUD",
    }


class CapturingTelemetry:
    name: str | None = None
    attributes: dict[str, object] | None = None

    @contextmanager
    def span(self, name: str, attributes: dict[str, object]):
        self.name = name
        self.attributes = attributes
        yield object()
