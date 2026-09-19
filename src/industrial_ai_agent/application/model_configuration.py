"""Application service for model catalog and persistent assignment configuration."""

from industrial_ai_agent.agent.llm import ModelId
from industrial_ai_agent.agent.model_egress import ModelExecutionAuthorizer
from industrial_ai_agent.agent.model_selection import (
    ModelAssignment,
    ModelAssignmentRepository,
    ModelCatalog,
    ModelConsumerDefinition,
    ModelConsumerId,
    ModelDefinition,
)
from industrial_ai_agent.domain.security import DataClassification


class ModelAssignmentPolicyError(PermissionError):
    code = "model_assignment_egress_denied"


class ModelConfigurationService:
    def __init__(
        self,
        *,
        catalog: ModelCatalog,
        assignments: ModelAssignmentRepository,
        supported_consumers: tuple[ModelConsumerId, ...],
        consumer_definitions: tuple[ModelConsumerDefinition, ...] = (),
        authorizer: ModelExecutionAuthorizer,
    ) -> None:
        self._catalog = catalog
        self._assignments = assignments
        self._supported_consumers = frozenset(supported_consumers)
        self._consumer_definitions = tuple(
            item
            for item in consumer_definitions
            if item.consumer_id in self._supported_consumers
        )
        self._authorizer = authorizer

    def list_models(self) -> tuple[ModelDefinition, ...]:
        return self._catalog.list_models()

    def list_assignments(self) -> tuple[ModelAssignment, ...]:
        return self._assignments.list()

    def list_consumers(self) -> tuple[ModelConsumerDefinition, ...]:
        return self._consumer_definitions

    def assign(
        self,
        *,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
        model_id: ModelId,
        updated_by: str | None = None,
    ) -> ModelAssignment:
        if consumer_id not in self._supported_consumers:
            raise ValueError("Unsupported model consumer")
        model = self._catalog.get_model(model_id.value)
        if not self._authorizer.is_allowed(
            data_classification,
            model.execution_zone,
            model.max_data_classification,
        ):
            raise ModelAssignmentPolicyError(
                "Model execution zone is not authorized for this classification"
            )
        return self._assignments.upsert(
            ModelAssignment(
                consumer_id=consumer_id,
                data_classification=data_classification,
                model_id=model_id,
                updated_by=updated_by,
            )
        )
