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
    ModelSelectionCandidate,
    ModelSelectionMode,
    ModelSelectionPolicy,
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
    quality: QualityClass = QualityClass.STANDARD,
    cost: CostClass = CostClass.LOW,
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
        quality_class=quality,
        cost_class=cost,
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


def _auto_resolver(
    *models: ModelDefinition,
    policy: ModelSelectionPolicy | None = ModelSelectionPolicy.QUALITY_FIRST,
    model_is_statically_available=None,
) -> ModelResolutionService:
    return ModelResolutionService(
        catalog=Catalog(*models),
        assignments=Assignments(
            ModelAssignment(
                consumer_id=VISION_VLM,
                data_classification=DataClassification.RESTRICTED,
                model_id=None,
                selection_mode=ModelSelectionMode.AUTO,
                selection_policy=policy,
            )
        ),
        authorizer=ModelExecutionAuthorizer(),
        consumer_requirements={VISION_VLM: VISION_REQUIREMENTS},
        model_is_statically_available=model_is_statically_available,
    )


def test_auto_quality_first_filters_capabilities_and_egress_before_ranking() -> None:
    decision = _auto_resolver(
        _model("local_medium", zone=ExecutionZone.LOCAL),
        _model(
            "local_high",
            zone=ExecutionZone.LOCAL,
            quality=QualityClass.HIGH,
            cost=CostClass.HIGH,
        ),
        _model(
            "public_high",
            zone=ExecutionZone.PUBLIC_CLOUD,
            quality=QualityClass.HIGH,
        ),
        _model(
            "local_text",
            zone=ExecutionZone.LOCAL,
            capabilities=frozenset({ModelCapability.TEXT}),
        ),
    ).resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert decision.model is not None
    assert decision.model.model_id == ModelId("local_high")
    assert decision.selection_mode is ModelSelectionMode.AUTO
    assert decision.selection_policy is ModelSelectionPolicy.QUALITY_FIRST
    exclusions = {
        item.model.model_id.value: item.exclusion_reason for item in decision.candidates
    }
    assert exclusions["local_text"] == "capability_mismatch"
    assert exclusions["public_high"] == "egress_denied"


def test_auto_cost_first_uses_stable_model_id_as_tie_breaker() -> None:
    decision = _auto_resolver(
        _model("local_z", zone=ExecutionZone.LOCAL, quality=QualityClass.HIGH),
        _model("local_a", zone=ExecutionZone.LOCAL, quality=QualityClass.HIGH),
        policy=ModelSelectionPolicy.COST_FIRST,
    ).resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert decision.model is not None
    assert decision.model.model_id == ModelId("local_a")


def test_auto_reports_capability_and_security_denials_separately() -> None:
    no_capabilities = _auto_resolver(
        _model(
            "local_text",
            zone=ExecutionZone.LOCAL,
            capabilities=frozenset({ModelCapability.TEXT}),
        )
    )
    only_public = _auto_resolver(
        _model("public_vision", zone=ExecutionZone.PUBLIC_CLOUD)
    )

    with pytest.raises(ModelResolutionError) as capability_error:
        no_capabilities.resolve_model(VISION_VLM, DataClassification.RESTRICTED)
    with pytest.raises(ModelResolutionError) as egress_error:
        only_public.resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert (
        capability_error.value.decision.outcome
        is ModelDecisionOutcome.CAPABILITY_MISMATCH
    )
    assert egress_error.value.decision.outcome is ModelDecisionOutcome.EGRESS_DENIED


def test_auto_excludes_statically_unavailable_models_before_ranking() -> None:
    configured = _model("configured", zone=ExecutionZone.LOCAL)
    unavailable = _model(
        "unavailable", zone=ExecutionZone.LOCAL, quality=QualityClass.HIGH
    )

    decision = _auto_resolver(
        configured,
        unavailable,
        model_is_statically_available=lambda model: (
            model.model_id == configured.model_id
        ),
    ).resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert decision.model == configured
    excluded = next(item for item in decision.candidates if item.model == unavailable)
    assert excluded.runtime_available is False
    assert excluded.capability_allowed is False
    assert excluded.egress_allowed is None
    assert excluded.exclusion_reason == "runtime_unavailable"


def test_auto_with_only_statically_unavailable_models_is_not_configured() -> None:
    with pytest.raises(ModelResolutionError) as captured:
        _auto_resolver(
            _model("unavailable", zone=ExecutionZone.LOCAL),
            model_is_statically_available=lambda _: False,
        ).resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert captured.value.decision.outcome is ModelDecisionOutcome.MODEL_NOT_CONFIGURED
    assert captured.value.decision.error_code == "model_runtime_unavailable"


def test_auto_without_policy_fails_closed_as_not_configured() -> None:
    resolver = _auto_resolver(
        _model("local_vision", zone=ExecutionZone.LOCAL), policy=None
    )

    with pytest.raises(ModelResolutionError) as captured:
        resolver.resolve_model(VISION_VLM, DataClassification.RESTRICTED)

    assert captured.value.decision.outcome is ModelDecisionOutcome.MODEL_NOT_CONFIGURED


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
        "model.selection_mode": "MANUAL",
        "run.id": str(run_id),
        "error.code": "model_egress_denied",
        "operation.duration_ms": 1.25,
        "model.id": "public_vision",
        "model.display_name": "Public Vision",
        "model.provider": "test",
        "execution.zone": "PUBLIC_CLOUD",
        "model.available_capabilities": "text,vision",
    }


def test_unconfigured_model_decision_uses_neutral_presentation_name() -> None:
    telemetry = CapturingTelemetry()
    observer = TelemetryModelDecisionObserver(telemetry)  # type: ignore[arg-type]

    observer.record(
        ModelDecision(
            consumer_id=VISION_VLM,
            effective_data_classification=DataClassification.RESTRICTED,
            required_capabilities=VISION_REQUIREMENTS,
            outcome=ModelDecisionOutcome.MODEL_NOT_CONFIGURED,
            error_code="model_not_configured",
        )
    )

    assert telemetry.attributes is not None
    assert telemetry.attributes["model.display_name"] == "Unconfigured model"
    assert "model.id" not in telemetry.attributes


def test_auto_candidate_trace_uses_safe_catalog_metadata_only() -> None:
    telemetry = CapturingTelemetry()
    capable = _model("local_vision", zone=ExecutionZone.LOCAL)
    rejected = _model("public_vision", zone=ExecutionZone.PUBLIC_CLOUD)

    TelemetryModelDecisionObserver(telemetry).record(  # type: ignore[arg-type]
        ModelDecision(
            consumer_id=VISION_VLM,
            effective_data_classification=DataClassification.RESTRICTED,
            required_capabilities=VISION_REQUIREMENTS,
            outcome=ModelDecisionOutcome.EXECUTION_ALLOWED,
            model=capable,
            capability_allowed=True,
            egress_allowed=True,
            selection_mode=ModelSelectionMode.AUTO,
            selection_policy=ModelSelectionPolicy.QUALITY_FIRST,
            candidates=(
                ModelSelectionCandidate(capable, True, True),
                ModelSelectionCandidate(rejected, True, False, "egress_denied"),
            ),
        )
    )

    candidate_spans = [
        item for item in telemetry.spans if item[0] == "model.selection.candidate"
    ]
    assert len(candidate_spans) == 2
    assert candidate_spans[1][1]["model.candidate_exclusion_reason"] == "egress_denied"
    assert "prompt" not in candidate_spans[0][1]
    assert "tool_result" not in candidate_spans[0][1]


class CapturingTelemetry:
    def __init__(self) -> None:
        self.name: str | None = None
        self.attributes: dict[str, object] | None = None
        self.spans: list[tuple[str, dict[str, object]]] = []

    @contextmanager
    def span(self, name: str, attributes: dict[str, object]):
        self.name = name
        self.attributes = attributes
        self.spans.append((name, attributes))
        yield object()

    def record_model_decision(self, *, attributes: dict[str, object]) -> None:
        assert attributes is not None
