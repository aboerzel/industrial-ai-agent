"""Isolated, content-free diagnostics for OpenAI-compatible provider contracts.

This module is deliberately outside model selection and production runtime wiring.
It exercises one explicit catalog model through the real adapter without Factory,
MCP, LangGraph, persisted assignments, routing, or egress policy.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from enum import StrEnum
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from industrial_ai_agent.agent.failure_origin import (
    FailureOrigin,
    failure_origin_for_error_code,
)
from industrial_ai_agent.agent.llm import (
    LLMJsonSchema,
    LLMMessage,
    LLMProviderError,
    LLMProviderErrorCode,
    LLMRequest,
    LLMResponseFormat,
    LLMToolDefinition,
    MessageRole,
    ModelId,
)
from industrial_ai_agent.agent.model_selection import (
    call_requirement_for_request,
    validate_model_capabilities,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    ModelCatalogConfiguration,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)


class CapabilityVerification(StrEnum):
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_VERIFIED = "NOT_VERIFIED"


class ProviderLiveStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_ERROR = "AUTH_ERROR"
    REQUEST_REJECTED = "REQUEST_REJECTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class ContractCallResult(BaseModel):
    """Metadata-only outcome of one synthetic provider call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verification: CapabilityVerification = CapabilityVerification.NOT_VERIFIED
    call_type: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    provider_http_status: int | None = Field(default=None, ge=100, le=599)
    provider_request_id: str | None = None
    provider_error_type: str | None = None
    provider_error_category: str | None = None
    provider_request_reason: str | None = None
    normalized_error: str | None = None
    failure_origin: FailureOrigin | None = None
    schema_hash: str | None = None
    request_payload_bytes: int | None = Field(default=None, ge=0)


class ProviderContractResult(BaseModel):
    """Ephemeral result suitable for JSON output, never routing or catalog state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    display_name: str
    provider: str
    provider_model: str
    execution_zone: str
    statically_configured: bool
    catalog_capabilities: tuple[str, ...]
    incompatible_capability_combinations: tuple[tuple[str, ...], ...]
    text: ContractCallResult = ContractCallResult()
    tool_calling: ContractCallResult = ContractCallResult()
    structured_output: ContractCallResult = ContractCallResult()
    multi_step: ContractCallResult = ContractCallResult()
    same_request_tools_structured: ContractCallResult = ContractCallResult()
    live_status: ProviderLiveStatus
    normalized_error: str | None = None
    failure_origin: FailureOrigin | None = None

    def safe_json(self) -> str:
        """Return the deliberately content-free, machine-readable diagnostic."""
        return self.model_dump_json(indent=2)


class _NestedItem(BaseModel):
    code: str
    quantity: int


class _ContractSeverity(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"


class _StructuredContractPayload(BaseModel):
    status: str
    optional_note: str | None
    retry_count: int = 0
    severity: _ContractSeverity
    detail: _NestedItem
    items: list[_NestedItem]


_TEST_TOOL = LLMToolDefinition(
    name="get_test_value",
    description="Return one harmless synthetic test value.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
)


def _structured_request() -> LLMRequest:
    schema = _StructuredContractPayload.model_json_schema()
    return LLMRequest(
        messages=(
            LLMMessage(
                role=MessageRole.USER,
                content=(
                    "Return JSON only. Set status to OK, optional_note to null, "
                    "severity to LOW, detail to {code: primary, quantity: 1}, and "
                    "items to [{code: item, quantity: 1}]."
                ),
            ),
        ),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name="provider_contract_payload",
                schema_definition=schema,
            )
        ),
    )


def _tool_request() -> LLMRequest:
    return LLMRequest(
        messages=(
            LLMMessage(
                role=MessageRole.USER,
                content="Call get_test_value with name set exactly to contract_value.",
            ),
        ),
        tools=(_TEST_TOOL,),
    )


def _plain_request() -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Reply with the word OK."),)
    )


class ProviderContractRunner:
    """Run minimal provider contracts using an explicit stable model ID only."""

    def __init__(
        self,
        configuration: ModelCatalogConfiguration,
        *,
        environment: Mapping[str, str] | None = None,
        client: OpenAICompatibleLLMClient | None = None,
    ) -> None:
        self._configuration = configuration
        self._environment = environment if environment is not None else os.environ
        self._client = client or OpenAICompatibleLLMClient(
            configuration, environment=self._environment
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def run(self, model_ids: Iterable[str]) -> tuple[ProviderContractResult, ...]:
        return tuple(self.run_model(model_id) for model_id in model_ids)

    def run_model(self, model_id: str) -> ProviderContractResult:
        config = self._configuration.get_model_config(model_id)
        configured = self._configuration.is_model_available(
            model_id, environment=self._environment
        )
        result = ProviderContractResult(
            model_id=model_id,
            display_name=config.display_name,
            provider=config.provider,
            provider_model=config.provider_model,
            execution_zone=config.execution_zone.value,
            statically_configured=configured,
            catalog_capabilities=tuple(
                sorted(item.value for item in config.capabilities)
            ),
            incompatible_capability_combinations=tuple(
                sorted(
                    tuple(sorted(item.value for item in combination))
                    for combination in config.incompatible_capability_combinations
                )
            ),
            live_status=(
                ProviderLiveStatus.AVAILABLE
                if configured
                else ProviderLiveStatus.NOT_CONFIGURED
            ),
            normalized_error=None if configured else "model_not_configured",
            failure_origin=(
                None
                if configured
                else failure_origin_for_error_code("model_not_configured")
            ),
        )
        if not configured:
            return result

        text, status = self._execute_plain(model_id)
        result = result.model_copy(update={"text": text, "live_status": status})
        result = self._with_top_level_error(result, text)
        if _stop_after(status):
            return result

        tools, status = self._execute_tools(model_id)
        result = result.model_copy(
            update={"tool_calling": tools, "live_status": status}
        )
        result = self._with_top_level_error(result, tools)
        if _stop_after(status):
            return result

        structured, status = self._execute_structured(model_id)
        result = result.model_copy(
            update={"structured_output": structured, "live_status": status}
        )
        result = self._with_top_level_error(result, structured)
        if _stop_after(status):
            return result

        multi_step, status = self._execute_multi_step(model_id)
        result = result.model_copy(
            update={"multi_step": multi_step, "live_status": status}
        )
        result = self._with_top_level_error(result, multi_step)
        if _stop_after(status):
            return result

        same_request = self._same_request_constraint(model_id)
        return result.model_copy(update={"same_request_tools_structured": same_request})

    def _execute_plain(
        self, model_id: str
    ) -> tuple[ContractCallResult, ProviderLiveStatus]:
        return self._execute(model_id, _plain_request(), _verify_plain)

    def _execute_tools(
        self, model_id: str
    ) -> tuple[ContractCallResult, ProviderLiveStatus]:
        return self._execute(model_id, _tool_request(), _verify_tool)

    def _execute_structured(
        self, model_id: str
    ) -> tuple[ContractCallResult, ProviderLiveStatus]:
        return self._execute(model_id, _structured_request(), _verify_structured)

    def _execute_multi_step(
        self, model_id: str
    ) -> tuple[ContractCallResult, ProviderLiveStatus]:
        tool, status = self._execute_tools(model_id)
        if (
            status is not ProviderLiveStatus.AVAILABLE
            or tool.verification is not CapabilityVerification.VERIFIED
        ):
            return tool, status
        structured, status = self._execute_structured(model_id)
        if (
            status is ProviderLiveStatus.AVAILABLE
            and structured.verification is CapabilityVerification.VERIFIED
        ):
            return (
                ContractCallResult(
                    verification=CapabilityVerification.VERIFIED,
                    call_type="multi_step_tool_then_structured",
                    duration_ms=(tool.duration_ms or 0) + (structured.duration_ms or 0),
                    schema_hash=structured.schema_hash,
                    request_payload_bytes=(tool.request_payload_bytes or 0)
                    + (structured.request_payload_bytes or 0),
                ),
                status,
            )
        return structured, status

    def _same_request_constraint(self, model_id: str) -> ContractCallResult:
        config = self._configuration.get_model_config(model_id)
        request = LLMRequest(
            messages=_plain_request().messages,
            tools=(_TEST_TOOL,),
            response_format=_structured_request().response_format,
        )
        validation = validate_model_capabilities(
            config.definition(), (call_requirement_for_request(request),)
        )
        if not validation.allowed and validation.incompatible_combination is not None:
            return ContractCallResult(
                verification=CapabilityVerification.UNSUPPORTED,
                call_type=call_requirement_for_request(request).call_type.value,
                normalized_error="model_capability_mismatch",
                failure_origin=failure_origin_for_error_code(
                    "model_capability_mismatch"
                ),
            )
        # No network request: unproven same-request support remains intentionally unknown.
        return ContractCallResult()

    def _execute(
        self,
        model_id: str,
        request: LLMRequest,
        verifier: Any,
    ) -> tuple[ContractCallResult, ProviderLiveStatus]:
        started = perf_counter()
        call_type = call_requirement_for_request(request).call_type.value
        try:
            response = self._client.chat(ModelId(model_id), request)
        except LLMProviderError as error:
            return _provider_error_result(error, perf_counter() - started, call_type)
        except ValueError:
            # Adapter configuration guards are deterministic local rejections.
            return (
                ContractCallResult(
                    call_type=call_type,
                    normalized_error="llm_provider_request_invalid",
                    failure_origin=failure_origin_for_error_code(
                        "llm_provider_request_invalid"
                    ),
                ),
                ProviderLiveStatus.REQUEST_REJECTED,
            )

        diagnostics = response.request_diagnostics
        metadata = {
            "call_type": call_type,
            "duration_ms": (perf_counter() - started) * 1000,
            "schema_hash": (
                diagnostics.structured_schema_hash if diagnostics is not None else None
            ),
            "request_payload_bytes": (
                diagnostics.request_payload_bytes if diagnostics is not None else None
            ),
        }
        try:
            verified = verifier(response)
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError):
            return (
                ContractCallResult(
                    **metadata,
                    normalized_error="model_output_invalid",
                    failure_origin=failure_origin_for_error_code(
                        "model_output_invalid"
                    ),
                ),
                ProviderLiveStatus.AVAILABLE,
            )
        return ContractCallResult(
            verification=verified, **metadata
        ), ProviderLiveStatus.AVAILABLE

    @staticmethod
    def _with_top_level_error(
        result: ProviderContractResult, call: ContractCallResult
    ) -> ProviderContractResult:
        if call.normalized_error is None:
            return result
        return result.model_copy(
            update={
                "normalized_error": call.normalized_error,
                "failure_origin": call.failure_origin,
            }
        )


def _verify_plain(response: Any) -> CapabilityVerification:
    if not isinstance(response.text, str) or not response.text.strip():
        raise ValueError("Expected a non-empty text response")
    return CapabilityVerification.VERIFIED


def _verify_tool(response: Any) -> CapabilityVerification:
    if len(response.tool_calls) != 1:
        raise ValueError("Expected exactly one synthetic tool call")
    tool_call = response.tool_calls[0]
    if tool_call.name != _TEST_TOOL.name or tool_call.arguments != {
        "name": "contract_value"
    }:
        raise ValueError("Synthetic tool call did not match the contract")
    return CapabilityVerification.VERIFIED


def _verify_structured(response: Any) -> CapabilityVerification:
    if not isinstance(response.text, str):
        raise TypeError("Expected structured response text")
    _StructuredContractPayload.model_validate_json(response.text)
    return CapabilityVerification.VERIFIED


def _provider_error_result(
    error: LLMProviderError, elapsed_seconds: float, call_type: str
) -> tuple[ContractCallResult, ProviderLiveStatus]:
    live_status = _live_status_for_error(error.code)
    diagnostics = error.request_diagnostics
    return (
        ContractCallResult(
            call_type=call_type,
            duration_ms=elapsed_seconds * 1000,
            provider_http_status=error.provider_http_status,
            provider_request_id=error.provider_request_id,
            provider_error_type=error.provider_error_type,
            provider_error_category=error.provider_error_category,
            provider_request_reason=error.provider_request_reason,
            normalized_error=error.code,
            failure_origin=failure_origin_for_error_code(error.code),
            schema_hash=(
                diagnostics.structured_schema_hash if diagnostics is not None else None
            ),
            request_payload_bytes=(
                diagnostics.request_payload_bytes if diagnostics is not None else None
            ),
        ),
        live_status,
    )


def _live_status_for_error(error_code: str) -> ProviderLiveStatus:
    if error_code in {
        LLMProviderErrorCode.RATE_LIMIT.value,
        LLMProviderErrorCode.QUOTA_EXCEEDED.value,
    }:
        return ProviderLiveStatus.RATE_LIMITED
    if error_code == LLMProviderErrorCode.PROVIDER_UNAVAILABLE.value:
        return ProviderLiveStatus.UNAVAILABLE
    return ProviderLiveStatus.REQUEST_REJECTED


def _stop_after(status: ProviderLiveStatus) -> bool:
    return status in {
        ProviderLiveStatus.RATE_LIMITED,
        ProviderLiveStatus.UNAVAILABLE,
        ProviderLiveStatus.AUTH_ERROR,
    }
