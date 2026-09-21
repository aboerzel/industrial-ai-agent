import pytest

from industrial_ai_agent.agent.user_severity import (
    UserSeverity,
    user_severity_for_terminal_outcome,
)


@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    (
        ("success", None, UserSeverity.SUCCESS),
        ("success", "requested_data_unavailable", UserSeverity.SUCCESS),
        ("limit_reached", None, UserSeverity.ATTENTION),
        ("failed", "requested_data_unavailable", UserSeverity.ATTENTION),
        ("failed", "llm_rate_limit", UserSeverity.ATTENTION),
        ("failed", "evidence_requirements_unsatisfied", UserSeverity.ATTENTION),
        ("failed", "evidence_source_unavailable", UserSeverity.ATTENTION),
        ("failed", "internal_error", UserSeverity.FAILURE),
        ("failed", "model_output_invalid", UserSeverity.FAILURE),
        ("failed", "agent_execution_timeout", UserSeverity.FAILURE),
        ("failed", "mcp_service_unavailable", UserSeverity.FAILURE),
        ("failed", "tool_execution_failed", UserSeverity.FAILURE),
    ),
)
def test_user_severity_is_derived_from_the_terminal_outcome_only(
    status: str, error_code: str | None, expected: UserSeverity
) -> None:
    assert (
        user_severity_for_terminal_outcome(status=status, error_code=error_code)
        is expected
    )
