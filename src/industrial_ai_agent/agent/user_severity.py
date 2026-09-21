"""Deterministic user-experience severity for terminal run outcomes."""

from enum import StrEnum


class UserSeverity(StrEnum):
    """Presentation semantics, deliberately independent from run diagnostics."""

    SUCCESS = "SUCCESS"
    ATTENTION = "ATTENTION"
    FAILURE = "FAILURE"


_ATTENTION_ERROR_CODES = frozenset(
    {
        "requested_data_unavailable",
        "diagnostic_target_unavailable",
        "llm_rate_limit",
        "llm_quota_exceeded",
        "evidence_requirements_unsatisfied",
        "evidence_source_unavailable",
    }
)


def user_severity_for_terminal_outcome(
    *, status: str, error_code: str | None = None
) -> UserSeverity:
    """Map one terminal turn only; prior investigation state is never an input."""
    if status == "success":
        return UserSeverity.SUCCESS
    if status == "limit_reached" or error_code in _ATTENTION_ERROR_CODES:
        return UserSeverity.ATTENTION
    return UserSeverity.FAILURE
