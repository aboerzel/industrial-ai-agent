"""Application service for model catalog and persistent assignment configuration."""

from collections.abc import Callable

from industrial_ai_agent.agent.llm import ModelId
from industrial_ai_agent.agent.model_egress import ModelExecutionAuthorizer
from industrial_ai_agent.agent.model_selection import (
    ModelAssignment,
    ModelAssignmentRepository,
    ModelCatalog,
    ModelConsumerDefinition,
    ModelConsumerId,
    ModelDefinition,
    ModelSelectionMode,
    ModelSelectionPolicy,
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
        model_is_statically_available: Callable[[ModelDefinition], bool] | None = None,
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
        self._model_is_statically_available = (
            model_is_statically_available or _always_statically_available
        )

    def list_models(self) -> tuple[ModelDefinition, ...]:
        return self._catalog.list_models()

    def is_model_statically_available(self, model: ModelDefinition) -> bool:
        """Expose configured-runtime availability without probing provider health."""

        return self._model_is_statically_available(model)

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
        return self.configure(
            consumer_id=consumer_id,
            data_classification=data_classification,
            selection_mode=ModelSelectionMode.MANUAL,
            model_id=model_id,
            updated_by=updated_by,
        )

    def configure(
        self,
        *,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
        selection_mode: ModelSelectionMode,
        model_id: ModelId | None = None,
        selection_policy: ModelSelectionPolicy | None = None,
        updated_by: str | None = None,
    ) -> ModelAssignment:
        if consumer_id not in self._supported_consumers:
            raise ValueError("Unsupported model consumer")
        if selection_mode is ModelSelectionMode.MANUAL:
            if model_id is None or selection_policy is not None:
                raise ValueError("Manual selection requires exactly one model")
            model = self._catalog.get_model(model_id.value)
            if not self._authorizer.is_allowed(
                data_classification,
                model.execution_zone,
                model.max_data_classification,
            ):
                raise ModelAssignmentPolicyError(
                    "Model execution zone is not authorized for this classification"
                )
        elif selection_mode is ModelSelectionMode.AUTO:
            if model_id is not None or selection_policy is None:
                raise ValueError("Automatic selection requires exactly one policy")
        else:
            raise ValueError("Unsupported model selection mode")
        return self._assignments.upsert(
            ModelAssignment(
                consumer_id=consumer_id,
                data_classification=data_classification,
                model_id=model_id,
                selection_mode=selection_mode,
                selection_policy=selection_policy,
                updated_by=updated_by,
            )
        )


def _always_statically_available(_: ModelDefinition) -> bool:
    """Keep catalog-only application tests independent of deployment configuration."""

    return True
