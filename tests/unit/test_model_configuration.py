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
        capabilities=frozenset({ModelCapability.TEXT}),
        quality_class=QualityClass.STANDARD,
        cost_class=CostClass.LOW,
    )


def _service() -> ModelConfigurationService:
    return ModelConfigurationService(
        catalog=Catalog(),
        assignments=Assignments(),
        supported_consumers=(AGENT_CONSUMER,),
        consumer_definitions=CURRENT_MODEL_CONSUMERS,
        authorizer=ModelExecutionAuthorizer(),
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
