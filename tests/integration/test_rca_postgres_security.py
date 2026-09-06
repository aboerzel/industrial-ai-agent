"""Live RLS verification for the RCA runtime-before-telemetry invariant."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest

from industrial_ai_agent.application.rca_analysis import RcaEvidenceCollector
from industrial_ai_agent.application.rca_evidence import RcaRunNotAccessibleError
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.rca_evidence import (
    StoreBackedRuntimeRcaEvidenceAdapter,
)

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires FACTORY_DATABASE_URL for the local PostgreSQL integration service",
)


class TraceMustNotBeCalled:
    def __init__(self) -> None:
        self.calls = 0

    def get_run_trace(self, run_id: UUID) -> object:
        self.calls += 1
        raise AssertionError(f"Telemetry lookup must not occur for {run_id}")


class UnusedLogs:
    def get_trace_logs(self, trace: object) -> tuple[object, ...]:
        raise AssertionError("Log lookup must not occur")


class UnusedMetrics:
    def get_trace_metrics(self, trace: object) -> tuple[object, ...]:
        raise AssertionError("Metric lookup must not occur")


def test_rca_denies_telemetry_before_trace_correlation_for_hidden_run() -> None:
    assert DATABASE_URL is not None
    run_id = uuid4()
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    confidential_context = _context(DataClassification.CONFIDENTIAL)
    public_context = _context(DataClassification.PUBLIC)
    trace = TraceMustNotBeCalled()
    try:
        asyncio.run(
            PostgreSqlAgentRunStore(factory, confidential_context).create(
                run_id,
                request_text="RCA RLS verification record",
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
        collector = RcaEvidenceCollector(
            runtime=StoreBackedRuntimeRcaEvidenceAdapter(
                lambda context: PostgreSqlAgentRunStore(factory, context)
            ),
            trace=trace,  # type: ignore[arg-type]
            logs=UnusedLogs(),  # type: ignore[arg-type]
            metrics=UnusedMetrics(),  # type: ignore[arg-type]
        )

        with pytest.raises(RcaRunNotAccessibleError):
            asyncio.run(collector.collect(run_id, public_context))
    finally:
        factory.dispose()

    assert trace.calls == 0


def _context(clearance: DataClassification) -> SecurityContext:
    return SecurityContext(
        subject_id=f"rca-security-{clearance.name.lower()}",
        roles=("test-engineer",),
        clearance=clearance,
        authenticated=False,
    )
