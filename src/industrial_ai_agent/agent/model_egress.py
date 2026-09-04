from enum import StrEnum
from typing import Protocol

from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    ModelProfile,
)
from industrial_ai_agent.domain.security import (
    DataClassification,
    effective_data_classification,
)


class ExecutionZone(StrEnum):
    LOCAL = "LOCAL"
    PUBLIC_CLOUD = "PUBLIC_CLOUD"


class ModelEgressDeniedError(RuntimeError):
    pass


class ModelExecutionZoneResolver(Protocol):
    def get_execution_zone(self, profile_name: str) -> object | None: ...


class ModelEgressPolicy:
    _ALLOWED_COMBINATIONS = frozenset(
        {
            (DataClassification.PUBLIC, ExecutionZone.LOCAL),
            (DataClassification.PUBLIC, ExecutionZone.PUBLIC_CLOUD),
            (DataClassification.INTERNAL, ExecutionZone.LOCAL),
            (DataClassification.CONFIDENTIAL, ExecutionZone.LOCAL),
            (DataClassification.RESTRICTED, ExecutionZone.LOCAL),
        }
    )

    def is_allowed(
        self,
        data_classification: object | None,
        execution_zone: object | None,
    ) -> bool:
        if not isinstance(data_classification, DataClassification):
            return False
        if not isinstance(execution_zone, ExecutionZone):
            return False
        return (data_classification, execution_zone) in self._ALLOWED_COMBINATIONS

    def require_allowed(
        self,
        data_classification: object | None,
        execution_zone: object | None,
    ) -> None:
        if not self.is_allowed(data_classification, execution_zone):
            raise ModelEgressDeniedError("Model egress denied by policy")


class EgressCheckedLLMClient:
    def __init__(
        self,
        delegate: LLMClient,
        execution_zone_resolver: ModelExecutionZoneResolver,
        request_classification: DataClassification | None,
        *,
        policy: ModelEgressPolicy | None = None,
    ) -> None:
        self._delegate = delegate
        self._execution_zone_resolver = execution_zone_resolver
        self._request_classification = request_classification
        self._policy = policy or ModelEgressPolicy()

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        execution_zone = self._execution_zone_resolver.get_execution_zone(profile.name)
        self._policy.require_allowed(
            self._request_classification,
            execution_zone,
        )
        return self._delegate.chat(profile, request)

    def raise_request_classification(self, classification: DataClassification) -> None:
        """Monotonically retain the highest classified data observed in this run."""
        self._request_classification = effective_data_classification(
            self._request_classification or classification,
            classification,
        )
