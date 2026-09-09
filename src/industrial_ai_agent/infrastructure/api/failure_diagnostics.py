"""Bounded, payload-free diagnostics for unexpected agent-run failures."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from industrial_ai_agent.agent.agent_run import (
    FinalAgentOutputContractError,
    InvalidToolArgumentsError,
    MissingLLMResponseTextError,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpServiceUnavailableError,
)

MAX_INNER_EXCEPTIONS = 4


@dataclass(frozen=True, slots=True)
class SanitizedFailureDiagnostic:
    """Safe metadata for one inner exception, with no exception text or traceback."""

    exception_type: str
    operation: str
    safe_error_code: str
    sanitized_reason: str


def summarize_failure(error: BaseException) -> tuple[SanitizedFailureDiagnostic, ...]:
    """Flatten an exception group into a small, closed set of safe diagnostics."""
    inner_exceptions = tuple(_leaf_exceptions(error))[:MAX_INNER_EXCEPTIONS]
    return tuple(_diagnostic_for(inner) for inner in inner_exceptions)


def _leaf_exceptions(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for inner in error.exceptions:
            leaves.extend(_leaf_exceptions(inner))
            if len(leaves) >= MAX_INNER_EXCEPTIONS:
                break
        return leaves
    return [error]


def _diagnostic_for(error: BaseException) -> SanitizedFailureDiagnostic:
    if isinstance(error, FinalAgentOutputContractError):
        if _is_reserved_final_answer_section(error):
            return SanitizedFailureDiagnostic(
                exception_type=type(error).__name__,
                operation="final_answer_contract_validation",
                safe_error_code="reserved_final_answer_section",
                sanitized_reason="final answer used a reserved structured section",
            )
        return SanitizedFailureDiagnostic(
            exception_type=type(error).__name__,
            operation="final_output_normalization",
            safe_error_code="invalid_structured_final_output",
            sanitized_reason="invalid structured final output shape",
        )
    if isinstance(error, ValidationError):
        return SanitizedFailureDiagnostic(
            exception_type=type(error).__name__,
            operation="final_output_normalization",
            safe_error_code="invalid_structured_final_output",
            sanitized_reason="invalid structured final output shape",
        )
    if isinstance(error, MissingLLMResponseTextError):
        return SanitizedFailureDiagnostic(
            exception_type=type(error).__name__,
            operation="model_response_validation",
            safe_error_code="missing_model_response_text",
            sanitized_reason="model response did not contain text",
        )
    if isinstance(error, InvalidToolArgumentsError):
        return SanitizedFailureDiagnostic(
            exception_type=type(error).__name__,
            operation="tool_execution",
            safe_error_code="invalid_tool_arguments",
            sanitized_reason="tool arguments failed validation",
        )
    if isinstance(error, McpServiceUnavailableError):
        return SanitizedFailureDiagnostic(
            exception_type=type(error).__name__,
            operation="mcp_transport",
            safe_error_code="mcp_service_unavailable",
            sanitized_reason="MCP service was unavailable",
        )
    if isinstance(error, KeyError):
        return SanitizedFailureDiagnostic(
            exception_type="KeyError",
            operation="langgraph_execution",
            safe_error_code="missing_runtime_value",
            sanitized_reason="required runtime value was missing",
        )
    if isinstance(error, TypeError):
        return SanitizedFailureDiagnostic(
            exception_type="TypeError",
            operation="langgraph_execution",
            safe_error_code="unexpected_runtime_type",
            sanitized_reason="unexpected runtime type",
        )
    if isinstance(error, ValueError):
        return SanitizedFailureDiagnostic(
            exception_type="ValueError",
            operation="langgraph_execution",
            safe_error_code="invalid_runtime_value",
            sanitized_reason="invalid runtime value",
        )
    return SanitizedFailureDiagnostic(
        exception_type=_safe_exception_type(error),
        operation="langgraph_execution",
        safe_error_code="unexpected_agent_runtime_error",
        sanitized_reason="unexpected agent runtime failure",
    )


def _safe_exception_type(error: BaseException) -> str:
    exception_type = type(error).__name__
    if exception_type.isidentifier() and len(exception_type) <= 80:
        return exception_type
    return "UnexpectedRuntimeError"


def _is_reserved_final_answer_section(error: FinalAgentOutputContractError) -> bool:
    return str(error).startswith(
        "Final answer contains a forbidden action section:"
    ) or str(error).startswith(
        "Final answer contains a forbidden investigation summary section:"
    )
