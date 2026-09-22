from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from industrial_ai_agent.agent.llm import ModelId
from industrial_ai_agent.agent.model_egress import (
    ExecutionZone,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_CONSUMER,
    CURRENT_MODEL_CONSUMERS,
    RCA_REASONING_CONSUMER,
    CostClass,
    ModelAssignment,
    ModelCapability,
    ModelDefinition,
    ModelSelectionMode,
    ModelSelectionPolicy,
    QualityClass,
)
from industrial_ai_agent.application.model_configuration import (
    ModelAssignmentPolicyError,
    ModelConfigurationService,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore


class Catalog:
    def __init__(self) -> None:
        self.models = {
            "local": _model("local", ExecutionZone.LOCAL),
            "local_quality": _model("local_quality", ExecutionZone.LOCAL),
            "local_alternative": _model("local_alternative", ExecutionZone.LOCAL),
            "public": _model("public", ExecutionZone.PUBLIC_CLOUD),
        }

    def get_model(self, model_id):
        try:
            return self.models[model_id]
        except KeyError as error:
            raise ValueError("Unknown model ID") from error

    def list_models(self):
        return tuple(self.models.values())


class Assignments:
    def __init__(self) -> None:
        self.values = {}

    def get(self, consumer_id, data_classification):
        return self.values.get((consumer_id, data_classification))

    def list(self):
        return tuple(self.values.values())

    def upsert(self, assignment):
        persisted = ModelAssignment(
            consumer_id=assignment.consumer_id,
            data_classification=assignment.data_classification,
            model_id=assignment.model_id,
            selection_mode=assignment.selection_mode,
            selection_policy=assignment.selection_policy,
            updated_at=datetime(2026, 9, 19, tzinfo=UTC),
            updated_by=assignment.updated_by,
        )
        self.values[(assignment.consumer_id, assignment.data_classification)] = (
            persisted
        )
        return persisted


def _model(model_id: str, zone: ExecutionZone) -> ModelDefinition:
    return ModelDefinition(
        model_id=ModelId(model_id),
        display_name=model_id.title(),
        provider="test",
        provider_model=f"test/{model_id}",
        execution_zone=zone,
        max_data_classification=(
            DataClassification.RESTRICTED
            if zone is ExecutionZone.LOCAL
            else DataClassification.CONFIDENTIAL
        ),
        capabilities=frozenset(
            {
                ModelCapability.TEXT,
                ModelCapability.TOOL_CALLING,
                ModelCapability.STRUCTURED_OUTPUT,
            }
        ),
        quality_class=QualityClass.STANDARD,
        cost_class=CostClass.LOW,
    )


def _service(
    *,
    assignments=None,
    supported_consumers=(AGENT_CONSUMER,),
    model_is_statically_available=None,
) -> ModelConfigurationService:
    return ModelConfigurationService(
        catalog=Catalog(),
        assignments=assignments or Assignments(),
        supported_consumers=supported_consumers,
        consumer_definitions=CURRENT_MODEL_CONSUMERS,
        authorizer=ModelExecutionAuthorizer(),
        model_is_statically_available=model_is_statically_available,
    )


def test_bootstrap_creates_missing_assignments_with_local_quality_manual_mode() -> None:
    assignments = Assignments()
    service = _service(
        assignments=assignments,
        supported_consumers=(AGENT_CONSUMER, RCA_REASONING_CONSUMER),
    )

    created = service.ensure_default_assignments()

    assert len(created) == len(DataClassification) * 2
    for consumer_id in (AGENT_CONSUMER, RCA_REASONING_CONSUMER):
        for classification in DataClassification:
            assignment = assignments.get(consumer_id, classification)
            assert assignment is not None
            assert assignment.model_id == ModelId("local_quality")
            assert assignment.selection_mode is ModelSelectionMode.MANUAL
            assert assignment.selection_policy is None
    assert service.ensure_default_assignments() == ()
    assert len(assignments.values) == len(DataClassification) * 2


def test_bootstrap_preserves_existing_choices_and_cross_consumer_rows() -> None:
    assignments = Assignments()
    service = _service(
        assignments=assignments,
        supported_consumers=(AGENT_CONSUMER, RCA_REASONING_CONSUMER),
    )
    service.ensure_default_assignments()
    service.assign(
        consumer_id=AGENT_CONSUMER,
        data_classification=DataClassification.PUBLIC,
        model_id=ModelId("local_alternative"),
        updated_by="operator",
    )
    restricted_before = assignments.get(AGENT_CONSUMER, DataClassification.RESTRICTED)

    service.ensure_default_assignments()
    service.assign(
        consumer_id=RCA_REASONING_CONSUMER,
        data_classification=DataClassification.PUBLIC,
        model_id=ModelId("local_alternative"),
        updated_by="operator",
    )

    assert assignments.get(
        AGENT_CONSUMER, DataClassification.PUBLIC
    ).model_id == ModelId("local_alternative")
    assert (
        assignments.get(AGENT_CONSUMER, DataClassification.RESTRICTED)
        == restricted_before
    )
    assert assignments.get(
        RCA_REASONING_CONSUMER, DataClassification.PUBLIC
    ).model_id == ModelId("local_alternative")


def test_bootstrap_preserves_existing_automatic_selection_and_attribution() -> None:
    assignments = Assignments()
    existing = ModelAssignment(
        consumer_id=AGENT_CONSUMER,
        data_classification=DataClassification.RESTRICTED,
        model_id=None,
        selection_mode=ModelSelectionMode.AUTO,
        selection_policy=ModelSelectionPolicy.QUALITY_FIRST,
        updated_by="operator:carol",
    )
    assignments.upsert(existing)
    service = _service(
        assignments=assignments,
        supported_consumers=(AGENT_CONSUMER, RCA_REASONING_CONSUMER),
    )

    service.ensure_default_assignments()

    assert assignments.get(AGENT_CONSUMER, DataClassification.RESTRICTED) == (
        ModelAssignment(
            consumer_id=AGENT_CONSUMER,
            data_classification=DataClassification.RESTRICTED,
            model_id=None,
            selection_mode=ModelSelectionMode.AUTO,
            selection_policy=ModelSelectionPolicy.QUALITY_FIRST,
            updated_at=datetime(2026, 9, 19, tzinfo=UTC),
            updated_by="operator:carol",
        )
    )


def test_assignment_cannot_grant_restricted_public_egress() -> None:
    with pytest.raises(ModelAssignmentPolicyError):
        _service().assign(
            consumer_id=AGENT_CONSUMER,
            data_classification=DataClassification.RESTRICTED,
            model_id=ModelId("public"),
        )


def test_configuration_api_uses_model_id_and_rejects_forbidden_assignment() -> None:
    app = create_app(
        object(),
        run_store=InMemoryAgentRunStore(),
        model_configuration_service=_service(),
    )
    client = TestClient(app)

    models = client.get("/api/v1/models")
    denied = client.put(
        "/api/v1/model-assignments",
        json={
            "consumer_id": "agent",
            "data_classification": "RESTRICTED",
            "model_id": "public",
        },
    )
    allowed = client.put(
        "/api/v1/model-assignments",
        json={
            "consumer_id": "agent",
            "data_classification": "RESTRICTED",
            "model_id": "local",
            "selection_mode": "MANUAL",
            "selection_policy": None,
        },
    )
    assignments = client.get("/api/v1/model-assignments")

    assert models.status_code == 200
    assert models.json()[0]["model_id"] == "local"
    assert "display_name" in models.json()[0]
    assert models.json()[0]["max_data_classification"] == "RESTRICTED"
    assert models.json()[0]["runtime_available"] is True
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "model_assignment_egress_denied"
    assert allowed.status_code == 200
    assert allowed.json()["model_id"] == "local"
    assert assignments.status_code == 200
    assert assignments.json() == [
        {
            "consumer_id": "agent",
            "data_classification": "RESTRICTED",
            "model_id": "local",
            "selection_mode": "MANUAL",
            "selection_policy": None,
            "updated_at": "2026-09-19T00:00:00+00:00",
            "updated_by": "api",
        }
    ]


def test_configuration_api_lists_supported_consumers_with_display_names() -> None:
    app = create_app(
        object(),
        run_store=InMemoryAgentRunStore(),
        model_configuration_service=_service(),
    )

    response = TestClient(app).get("/api/v1/model-consumers")

    assert response.status_code == 200
    assert response.json()[0]["consumer_id"] == "agent"
    assert response.json()[0]["display_name"] == "Agent"
    assert set(response.json()[0]["required_capabilities"]) == {
        "structured_output",
        "text",
        "tool_calling",
    }
    requirements = {
        item["call_type"]: set(item["required_capabilities"])
        for item in response.json()[0]["call_requirements"]
    }
    assert requirements == {
        "tool_decision": {"text", "tool_calling"},
        "structured_response": {"text", "structured_output"},
        "plain_text": {"text"},
    }


def test_catalog_api_keeps_statically_unavailable_models_visible() -> None:
    app = create_app(
        object(),
        run_store=InMemoryAgentRunStore(),
        model_configuration_service=_service(
            model_is_statically_available=lambda _: False
        ),
    )

    response = TestClient(app).get("/api/v1/models")

    assert response.status_code == 200
    assert [item["model_id"] for item in response.json()] == [
        "local",
        "local_quality",
        "local_alternative",
        "public",
    ]
    assert all(item["runtime_available"] is False for item in response.json())


def test_configuration_api_rejects_unknown_model_and_consumer() -> None:
    app = create_app(
        object(),
        run_store=InMemoryAgentRunStore(),
        model_configuration_service=_service(),
    )
    client = TestClient(app)

    unknown_model = client.put(
        "/api/v1/model-assignments",
        json={
            "consumer_id": "agent",
            "data_classification": "PUBLIC",
            "model_id": "missing",
        },
    )
    unknown_consumer = client.put(
        "/api/v1/model-assignments",
        json={
            "consumer_id": "vision.vlm",
            "data_classification": "PUBLIC",
            "model_id": "local",
        },
    )

    assert unknown_model.status_code == 400
    assert unknown_model.json()["detail"]["code"] == "invalid_model_assignment"
    assert unknown_consumer.status_code == 400
    assert unknown_consumer.json()["detail"]["code"] == "invalid_model_assignment"


def test_configuration_api_persists_auto_policy_without_model_id() -> None:
    service = _service()
    app = create_app(
        object(),
        run_store=InMemoryAgentRunStore(),
        model_configuration_service=service,
    )

    response = TestClient(app).put(
        "/api/v1/model-assignments",
        json={
            "consumer_id": "agent",
            "data_classification": "RESTRICTED",
            "model_id": None,
            "selection_mode": "AUTO",
            "selection_policy": "QUALITY_FIRST",
        },
    )

    assert response.status_code == 200
    assert response.json()["model_id"] is None
    assert response.json()["selection_mode"] == ModelSelectionMode.AUTO
    assert response.json()["selection_policy"] == ModelSelectionPolicy.QUALITY_FIRST
