"""Shared classification visibility policy for persisted runs and derived metadata."""

from industrial_ai_agent.domain.security import DataClassification, SecurityContext


def is_run_visible(
    classification: DataClassification, security_context: SecurityContext
) -> bool:
    """Fail closed for unknown labels; preserve the API's clearance ordering."""
    return (
        isinstance(classification, DataClassification)
        and classification <= security_context.clearance
    )
