from evals.run_outcome import AcceptanceOutcome, classify_run_outcome


def test_llm_rate_and_quota_limits_block_acceptance_without_failing_it() -> None:
    assert (
        classify_run_outcome(status="failed", error_code="llm_rate_limit")
        is AcceptanceOutcome.BLOCKED_BY_PROVIDER
    )
    assert (
        classify_run_outcome(status="failed", error_code="llm_quota_exceeded")
        is AcceptanceOutcome.BLOCKED_BY_PROVIDER
    )
    assert (
        classify_run_outcome(status="failed", error_code="llm_provider_unavailable")
        is AcceptanceOutcome.BLOCKED_BY_PROVIDER
    )


def test_internal_error_is_a_functional_acceptance_failure() -> None:
    assert (
        classify_run_outcome(status="failed", error_code="internal_error")
        is AcceptanceOutcome.FAIL
    )


def test_verified_provider_limit_evidence_wins_over_an_outer_timeout() -> None:
    assert (
        classify_run_outcome(
            status="failed",
            error_code="agent_execution_timeout",
            provider_error_code="llm_rate_limit",
        )
        is AcceptanceOutcome.BLOCKED_BY_PROVIDER
    )


def test_timeout_without_provider_evidence_remains_a_functional_failure() -> None:
    assert (
        classify_run_outcome(
            status="failed",
            error_code="agent_execution_timeout",
        )
        is AcceptanceOutcome.FAIL
    )
