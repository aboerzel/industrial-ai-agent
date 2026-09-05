"""Safe LLM telemetry adapter at the existing provider boundary."""

from time import perf_counter

from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    ModelProfile,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.llm.configuration import LLMConfiguration
from industrial_ai_agent.infrastructure.telemetry import Telemetry


class ObservedLLMClient:
    """Decorate an existing checked client without observing request/response content."""

    def __init__(
        self,
        delegate: LLMClient,
        *,
        configuration: LLMConfiguration,
        data_classification: DataClassification,
        telemetry: Telemetry,
    ) -> None:
        self._delegate = delegate
        self._configuration = configuration
        self._data_classification = data_classification
        self._telemetry = telemetry

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        profile_config = self._configuration.get_profile(profile.name)
        attributes = {
            "model.profile": profile.name,
            "model.name": profile_config.model,
            "execution.zone": profile_config.execution_zone.value,
            "data.classification": self._data_classification.name,
        }
        started = perf_counter()
        status = "success"
        try:
            with self._telemetry.span("llm.call", attributes):
                return self._delegate.chat(profile, request)
        except Exception:
            status = "failure"
            raise
        finally:
            self._telemetry.record_llm_call(
                attributes={**attributes, "operation.status": status},
                duration_seconds=perf_counter() - started,
            )

    def raise_request_classification(self, classification: DataClassification) -> None:
        """Preserve monotonic classification for both egress and telemetry metadata."""
        self._data_classification = max(self._data_classification, classification)
        raise_classification = getattr(
            self._delegate, "raise_request_classification", None
        )
        if callable(raise_classification):
            raise_classification(classification)
