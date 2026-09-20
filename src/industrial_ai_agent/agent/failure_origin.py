"""Coarse, stable attribution for failed agent runs.

Origins are diagnostic metadata only. They never participate in authorization,
model selection, retries, or provider execution.
"""

from enum import StrEnum


class FailureOrigin(StrEnum):
    MODEL_SELECTION = "MODEL_SELECTION"
    MODEL_AVAILABILITY = "MODEL_AVAILABILITY"
    CAPABILITY_VALIDATION = "CAPABILITY_VALIDATION"
    SECURITY_POLICY = "SECURITY_POLICY"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_CONNECTION = "PROVIDER_CONNECTION"
    PROVIDER_REQUEST = "PROVIDER_REQUEST"
    MODEL_OUTPUT_VALIDATION = "MODEL_OUTPUT_VALIDATION"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    MCP = "MCP"
    ORCHESTRATION = "ORCHESTRATION"
    PERSISTENCE = "PERSISTENCE"


_ERROR_ORIGINS: dict[str, FailureOrigin] = {
    "model_not_configured": FailureOrigin.MODEL_SELECTION,
    "model_runtime_unavailable": FailureOrigin.MODEL_AVAILABILITY,
    "model_capability_mismatch": FailureOrigin.CAPABILITY_VALIDATION,
    "model_egress_denied": FailureOrigin.SECURITY_POLICY,
    "llm_rate_limit": FailureOrigin.PROVIDER_RATE_LIMIT,
    "llm_quota_exceeded": FailureOrigin.PROVIDER_RATE_LIMIT,
    "llm_provider_unavailable": FailureOrigin.PROVIDER_CONNECTION,
    "llm_provider_request_invalid": FailureOrigin.PROVIDER_REQUEST,
    "mcp_service_unavailable": FailureOrigin.MCP,
    "model_output_invalid": FailureOrigin.MODEL_OUTPUT_VALIDATION,
    "tool_execution_failed": FailureOrigin.TOOL_EXECUTION,
    "agent_execution_timeout": FailureOrigin.ORCHESTRATION,
    "evidence_requirements_unsatisfied": FailureOrigin.ORCHESTRATION,
    "evidence_source_unavailable": FailureOrigin.ORCHESTRATION,
    "internal_error": FailureOrigin.ORCHESTRATION,
}


def failure_origin_for_error_code(error_code: str | None) -> FailureOrigin | None:
    """Return diagnostic attribution for a normalized error code, if known."""
    return _ERROR_ORIGINS.get(error_code or "")
