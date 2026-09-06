import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.application.rca import (
    RcaApprovalState,
    RcaMeasurementUnit,
    RcaOperation,
)
from industrial_ai_agent.application.rca_evidence import (
    RcaEvidenceMalformedError,
    RcaRunNotAccessibleError,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.run_store import RuntimeRunInspection
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.observability_backends import (
    MetricContext,
    MetricSeries,
    RunTrace,
    TraceLogEvent,
    TraceSpan,
)
from industrial_ai_agent.infrastructure.rca_evidence import (
    ObservabilityRcaEvidenceAdapter,
    StoreBackedRuntimeRcaEvidenceAdapter,
)

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
TRACE_ID = "0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 6, tzinfo=UTC)
CONTEXT = SecurityContext(
    subject_id="rca-adapter-test",
    roles=("engineer",),
    clearance=DataClassification.INTERNAL,
    authenticated=True,
)


class FakeRunStore:
    def __init__(self, inspection: RuntimeRunInspection | None) -> None:
        self.inspection = inspection
        self.seen_run_id: UUID | None = None

    async def inspect(self, run_id: UUID) -> RuntimeRunInspection | None:
        self.seen_run_id = run_id
        return self.inspection


class FakeObservabilityService:
    def get_run_trace(self, run_id: str) -> RunTrace:
        return RunTrace(
            run_id=run_id,
            trace_id=TRACE_ID,
            duration_ms=100,
            status="ok",
            participating_services=("industrial-ai-agent",),
            spans=(
                TraceSpan(
                    span_id="fedcba9876543210",
                    parent_span_id=None,
                    operation_name="POST /api/v1/diagnostics",
                    service_name="industrial-ai-agent",
                    start_time=NOW,
                    duration_ms=100,
                    status="unset",
                    attributes={},
                ),
                TraceSpan(
                    span_id="0123456789abcdef",
                    parent_span_id=None,
                    operation_name=RcaOperation.MCP_TOOL.value,
                    service_name="industrial-ai-agent",
                    start_time=NOW,
                    duration_ms=50,
                    status="ok",
                    attributes={
                        "mcp.tool": "get_machine_status",
                        "request.body": "secret",
                    },
                ),
            ),
        )

    def get_trace_logs(self, trace_id: str) -> tuple[TraceLogEvent, ...]:
        return (
            TraceLogEvent(
                timestamp=NOW,
                service_name="industrial-ai-agent",
                event_name="agent.run.completed",
                severity="info",
                trace_id=trace_id,
            ),
        )

    def get_run_metrics(self, trace_id: str) -> MetricContext:
        return MetricContext(
            start_time=NOW,
            end_time=NOW,
            source="trace_correlated_window",
            series=(MetricSeries(name="run_count", points=((NOW, 1),)),),
        )


def test_store_backed_adapter_uses_context_bound_store_and_safe_projection() -> None:
    store = FakeRunStore(_inspection())
    seen_context: SecurityContext | None = None

    def store_for_context(context: SecurityContext) -> FakeRunStore:
        nonlocal seen_context
        seen_context = context
        return store

    adapter = StoreBackedRuntimeRcaEvidenceAdapter(store_for_context)
    observation = asyncio.run(adapter.inspect_run(RUN_ID, CONTEXT))

    assert seen_context is CONTEXT
    assert store.seen_run_id == RUN_ID
    assert observation.data_classification is DataClassification.INTERNAL
    assert observation.approval_state is RcaApprovalState.APPROVED
    assert observation.error_code == "RUN_FAILED"


def test_store_backed_adapter_fails_closed_when_rls_filtered_run_is_absent() -> None:
    adapter = StoreBackedRuntimeRcaEvidenceAdapter(lambda _: FakeRunStore(None))

    with pytest.raises(RcaRunNotAccessibleError):
        asyncio.run(adapter.inspect_run(RUN_ID, CONTEXT))


def test_observability_adapter_keeps_only_bounded_safe_projections() -> None:
    adapter = ObservabilityRcaEvidenceAdapter(FakeObservabilityService())  # type: ignore[arg-type]

    trace = adapter.get_run_trace(RUN_ID)
    logs = adapter.get_trace_logs(trace)
    metrics = adapter.get_trace_metrics(trace)

    span = trace.spans[0]
    assert len(trace.spans) == 1
    assert span.operation is RcaOperation.MCP_TOOL
    assert [(item.name.value, item.value) for item in span.safe_attributes] == [
        ("mcp.tool", "get_machine_status")
    ]
    assert logs[0].event_name == "agent.run.completed"
    assert metrics[0].unit is RcaMeasurementUnit.COUNT
    assert "secret" not in repr(trace)


def test_observability_adapter_rejects_non_finite_metric_values() -> None:
    class NonFiniteMetrics(FakeObservabilityService):
        def get_run_metrics(self, trace_id: str) -> MetricContext:
            return MetricContext(
                start_time=NOW,
                end_time=NOW,
                source="trace_correlated_window",
                series=(MetricSeries(name="run_count", points=((NOW, float("nan")),)),),
            )

    adapter = ObservabilityRcaEvidenceAdapter(NonFiniteMetrics())  # type: ignore[arg-type]
    trace = adapter.get_run_trace(RUN_ID)

    with pytest.raises(RcaEvidenceMalformedError):
        adapter.get_trace_metrics(trace)


def _inspection() -> RuntimeRunInspection:
    return RuntimeRunInspection(
        run_id=RUN_ID,
        thread_id=RUN_ID,
        status=RunStatus.FAILED,
        data_classification=DataClassification.INTERNAL,
        run_profile=AgentRunProfile.INTERNAL_DIAGNOSTIC,
        model_profile="troubleshooting",
        tool_call_count=1,
        tool_names=("get_machine_status",),
        error_code="RUN_FAILED",
        approval_action="create_maintenance_ticket",
        approval_decision="approve",
        approval_requested_at=NOW,
        approval_decided_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
