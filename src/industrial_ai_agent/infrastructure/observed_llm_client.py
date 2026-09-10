"""Safe LLM telemetry adapter at the existing provider boundary."""

from time import perf_counter

from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMProviderError,
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
        operation_type: str | None = None,
        rca_focus: str | None = None,
    ) -> None:
        self._delegate = delegate
        self._configuration = configuration
        self._data_classification = data_classification
        self._telemetry = telemetry
        self._operation_type = operation_type
        self._rca_focus = rca_focus

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        profile_config = self._configuration.get_profile(profile.name)
        attributes = {
            "model.profile": profile.name,
            "model.name": profile_config.model,
            "model.provider": profile_config.provider,
            "execution.zone": profile_config.execution_zone.value,
            "data.classification": self._data_classification.name,
        }
        if self._operation_type is not None:
            attributes["operation.type"] = self._operation_type
        if self._rca_focus is not None:
            attributes["rca.focus"] = self._rca_focus
        started = perf_counter()
        status = "success"
        try:
            with self._telemetry.span("llm.call", attributes) as span:
                response = self._delegate.chat(profile, request)
                self._telemetry.set_span_attributes(
                    span,
                    _response_telemetry_attributes(
                        response, profile_config.api_cost_usd
                    ),
                )
                self._telemetry.record_llm_usage(
                    attributes={**attributes, "operation.status": status},
                    input_tokens=(
                        response.usage.input_tokens
                        if response.usage is not None
                        else None
                    ),
                    output_tokens=(
                        response.usage.output_tokens
                        if response.usage is not None
                        else None
                    ),
                    total_tokens=(
                        response.usage.total_tokens
                        if response.usage is not None
                        else None
                    ),
                )
                tool_name = _first_admitted_tool_name(response, request)
                if tool_name is not None:
                    self._telemetry.record_llm_tool_usage(
                        attributes={
                            **attributes,
                            "mcp.tool": tool_name,
                            "operation.status": status,
                        },
                        input_tokens=(
                            response.usage.input_tokens
                            if response.usage is not None
                            else None
                        ),
                        output_tokens=(
                            response.usage.output_tokens
                            if response.usage is not None
                            else None
                        ),
                        total_tokens=(
                            response.usage.total_tokens
                            if response.usage is not None
                            else None
                        ),
                    )
                return response
        except LLMProviderError as error:
            status = "failure"
            attributes.update(
                {
                    "error.code": error.code,
                    "error.stage": error.error_stage,
                }
            )
            raise
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


def _response_telemetry_attributes(
    response: LLMResponse, api_cost_usd: object | None
) -> dict[str, object]:
    """Expose only provider usage and explicitly configured API monetary cost."""
    attributes: dict[str, object] = {
        "telemetry.usage_status": "unavailable",
        "telemetry.cost_status": "unavailable",
    }
    if response.usage is not None:
        attributes["telemetry.usage_status"] = "provider_reported"
        if response.usage.input_tokens is not None:
            attributes["token.input_count"] = response.usage.input_tokens
        if response.usage.output_tokens is not None:
            attributes["token.output_count"] = response.usage.output_tokens
        if response.usage.total_tokens is not None:
            attributes["token.total_count"] = response.usage.total_tokens
    if api_cost_usd is not None:
        attributes["cost.api_usd"] = float(api_cost_usd)
        attributes["telemetry.cost_status"] = "configured_api_cost"
    return attributes


def _first_admitted_tool_name(response: LLMResponse, request: LLMRequest) -> str | None:
    """Return the one bounded tool decision the sequential graph can dispatch."""
    if not response.tool_calls:
        return None
    first_tool_name = response.tool_calls[0].name
    allowed_tool_names = {tool.name for tool in request.tools}
    return first_tool_name if first_tool_name in allowed_tool_names else None
