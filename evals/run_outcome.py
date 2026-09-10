"""Deterministic acceptance classification for persisted public run outcomes."""

from enum import StrEnum


class AcceptanceOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_BY_PROVIDER = "BLOCKED_BY_PROVIDER"


_PROVIDER_BLOCKED_ERROR_CODES = frozenset(
    {"llm_provider_unavailable", "llm_rate_limit", "llm_quota_exceeded"}
)


def classify_run_outcome(
    *,
    status: str,
    error_code: str | None,
    provider_error_code: str | None = None,
) -> AcceptanceOutcome:
    """Keep verified provider blocks separate from functional acceptance failures."""
    if provider_error_code in _PROVIDER_BLOCKED_ERROR_CODES:
        return AcceptanceOutcome.BLOCKED_BY_PROVIDER
    if error_code in _PROVIDER_BLOCKED_ERROR_CODES:
        return AcceptanceOutcome.BLOCKED_BY_PROVIDER
    if status == "failed":
        return AcceptanceOutcome.FAIL
    return AcceptanceOutcome.PASS
