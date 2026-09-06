"""Infrastructure adapters that project existing bounded evidence into RCA ports."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from uuid import UUID

from industrial_ai_agent.application.rca import (
    RcaApprovalState,
    RcaComponent,
    RcaMeasurementUnit,
    RcaOperation,
    RcaOperationStatus,
    RcaRuntimeStatus,
    RcaSafeAttributeName,
    RcaSeverity,
    RcaSpanAttribute,
)
from industrial_ai_agent.application.rca_evidence import (
    RcaEvidenceMalformedError,
    RcaEvidenceMissingError,
    RcaEvidenceUnavailableError,
    RcaLogObservation,
    RcaMetricObservation,
    RcaRunNotAccessibleError,
    RcaRuntimeEvidenceUnavailableError,
    RcaRuntimeObservation,
    RcaSpanObservation,
    RcaToolTrajectoryObservation,
    RcaTraceObservation,
)
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.api.run_store import (
    AgentRunStore,
    RuntimeRunInspection,
)
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.observability_backends import (
    MetricContext,
    ObservabilityBackendUnavailable,
    ObservabilityEvidenceService,
    ObservabilityMalformedResponse,
    ObservabilityNotFoundError,
    RunTrace,
    TraceLogEvent,
    TraceSpan,
)


class StoreBackedRuntimeRcaEvidenceAdapter:
    """Project RLS-filtered runtime inspections without exposing run payloads."""

    def __init__(
        self, store_for_context: Callable[[SecurityContext], AgentRunStore]
    ) -> None:
        self._store_for_context = store_for_context

    async def inspect_run(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RcaRuntimeObservation:
        inspection = await self._inspection(run_id, security_context)
        return RcaRuntimeObservation(
            run_id=inspection.run_id,
            status=RcaRuntimeStatus(inspection.status.value),
            data_classification=inspection.data_classification,
            run_profile=inspection.run_profile.value,
            model_profile=inspection.model_profile,
            created_at=inspection.created_at,
            updated_at=inspection.updated_at,
            error_code=inspection.error_code,
            tool_call_count=inspection.tool_call_count,
            approval_state=_approval_state(inspection),
            approval_requested_at=inspection.approval_requested_at,
            approval_decided_at=inspection.approval_decided_at,
        )

    async def get_tool_trajectory(
        self, run_id: UUID, security_context: SecurityContext
    ) -> tuple[RcaToolTrajectoryObservation, ...]:
        inspection = await self._inspection(run_id, security_context)
        return tuple(
            RcaToolTrajectoryObservation(
                sequence=index,
                tool_name=tool_name,
                component=_tool_component(tool_name),
            )
            for index, tool_name in enumerate(inspection.tool_names, start=1)
        )

    async def _inspection(
        self, run_id: UUID, security_context: SecurityContext
    ) -> RuntimeRunInspection:
        try:
            inspection = await self._store_for_context(security_context).inspect(run_id)
        except Exception as error:
            raise RcaRuntimeEvidenceUnavailableError(
                "RCA runtime evidence is unavailable"
            ) from error
        if inspection is None:
            raise RcaRunNotAccessibleError("The requested run is not accessible")
        return inspection


class ObservabilityRcaEvidenceAdapter:
    """Reuse bounded observability queries and translate their safe projections."""

    def __init__(self, evidence_service: ObservabilityEvidenceService) -> None:
        self._evidence_service = evidence_service

    def get_run_trace(self, run_id: UUID) -> RcaTraceObservation:
        try:
            trace = self._evidence_service.get_run_trace(str(run_id))
        except Exception as error:
            raise _translate_observability_error(error) from error
        return _trace_observation(trace)

    def get_trace_logs(
        self, trace: RcaTraceObservation
    ) -> tuple[RcaLogObservation, ...]:
        try:
            logs = self._evidence_service.get_trace_logs(trace.trace_id)
        except Exception as error:
            raise _translate_observability_error(error) from error
        return tuple(_log_observation(item) for item in logs)

    def get_trace_metrics(
        self, trace: RcaTraceObservation
    ) -> tuple[RcaMetricObservation, ...]:
        try:
            metrics = self._evidence_service.get_run_metrics(trace.trace_id)
        except Exception as error:
            raise _translate_observability_error(error) from error
        return _metric_observations(metrics)


def _trace_observation(trace: RunTrace) -> RcaTraceObservation:
    try:
        spans = tuple(
            observation
            for span in trace.spans
            if (observation := _span_observation(span)) is not None
        )
        return RcaTraceObservation(
            trace_id=trace.trace_id,
            spans=spans,
            truncated=trace.truncated,
        )
    except (TypeError, ValueError) as error:
        raise RcaEvidenceMalformedError(
            "Tempo evidence could not be safely projected"
        ) from error


def _span_observation(span: TraceSpan) -> RcaSpanObservation | None:
    operation_name = span.operation_name
    service_name = span.service_name
    try:
        operation = RcaOperation(operation_name)
    except ValueError:
        return None
    return RcaSpanObservation(
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        operation=operation,
        component=_operation_component(operation_name),
        service=_service_component(service_name),
        started_at=span.start_time,
        duration_ms=span.duration_ms,
        status=RcaOperationStatus(span.status),
        error_type=span.error_type,
        error_code=span.error_code,
        safe_attributes=tuple(
            RcaSpanAttribute(name=RcaSafeAttributeName(name), value=value)
            for name, value in span.attributes.items()
            if name in {item.value for item in RcaSafeAttributeName}
        ),
    )


def _log_observation(event: TraceLogEvent) -> RcaLogObservation:
    try:
        return RcaLogObservation(
            timestamp=event.timestamp,
            component=_service_component(event.service_name),
            event_name=event.event_name,
            severity=_log_severity(event.severity),
            error_code=event.error_code,
        )
    except (TypeError, ValueError) as error:
        raise RcaEvidenceMalformedError(
            "Loki evidence could not be safely projected"
        ) from error


def _metric_observations(context: MetricContext) -> tuple[RcaMetricObservation, ...]:
    try:
        return tuple(
            RcaMetricObservation(
                metric_name=series.name,
                value=point_value,
                unit=_metric_unit(series.name),
                window_start=context.start_time,
                window_end=context.end_time,
            )
            for series in context.series
            for _, point_value in series.points
            if _finite_metric_value(point_value)
        )
    except (TypeError, ValueError) as error:
        raise RcaEvidenceMalformedError(
            "Prometheus evidence could not be safely projected"
        ) from error


def _finite_metric_value(value: float) -> bool:
    if not isfinite(value):
        raise ValueError("Metric value must be finite")
    return True


def _translate_observability_error(error: Exception) -> Exception:
    if isinstance(error, ObservabilityBackendUnavailable):
        return RcaEvidenceUnavailableError("Observability backend is unavailable")
    if isinstance(error, ObservabilityNotFoundError):
        return RcaEvidenceMissingError("Observability evidence was not recorded")
    if isinstance(error, ObservabilityMalformedResponse):
        return RcaEvidenceMalformedError("Observability evidence is malformed")
    if isinstance(
        error,
        (
            RcaEvidenceUnavailableError,
            RcaEvidenceMissingError,
            RcaEvidenceMalformedError,
        ),
    ):
        return error
    return RcaEvidenceMalformedError("Observability evidence could not be projected")


def _approval_state(inspection: RuntimeRunInspection) -> RcaApprovalState:
    if inspection.status is RunStatus.WAITING_FOR_APPROVAL:
        return RcaApprovalState.WAITING
    if inspection.approval_decision == "approve":
        return RcaApprovalState.APPROVED
    if inspection.approval_decision == "reject":
        return RcaApprovalState.REJECTED
    return RcaApprovalState.NONE


def _tool_component(tool_name: str) -> RcaComponent:
    if tool_name == "search_documentation":
        return RcaComponent.KNOWLEDGE_MCP
    if tool_name in {"get_machine_status", "get_product_history"}:
        return RcaComponent.FACTORY_MCP
    return RcaComponent.MCP


def _operation_component(operation: str) -> RcaComponent:
    if operation == RcaOperation.LLM_CALL.value:
        return RcaComponent.LLM
    if (
        operation.startswith("retrieval.")
        or operation == RcaOperation.KNOWLEDGE_SEARCH.value
    ):
        return RcaComponent.RETRIEVAL
    if operation == RcaOperation.MCP_DISCOVERY.value:
        return RcaComponent.MCP_DISCOVERY
    if operation in {RcaOperation.MCP_TOOL.value, RcaOperation.FACTORY_TOOL.value}:
        return RcaComponent.MCP
    if operation.startswith("approval."):
        return RcaComponent.APPROVAL
    if operation.startswith("persistence."):
        return RcaComponent.PERSISTENCE
    if operation == RcaOperation.MODEL_ROUTING.value:
        return RcaComponent.MODEL_ROUTING
    return RcaComponent.AGENT_RUNTIME


def _service_component(service_name: str) -> RcaComponent:
    return {
        "industrial-ai-agent": RcaComponent.AGENT_RUNTIME,
        "factory-mcp": RcaComponent.FACTORY_MCP,
        "knowledge-mcp": RcaComponent.KNOWLEDGE_MCP,
        "observability-mcp": RcaComponent.TELEMETRY,
        "runtime-mcp": RcaComponent.AGENT_RUNTIME,
    }.get(service_name, RcaComponent.UNKNOWN)


def _log_severity(severity: str) -> RcaSeverity:
    return {
        "debug": RcaSeverity.INFO,
        "info": RcaSeverity.INFO,
        "warning": RcaSeverity.WARNING,
        "warn": RcaSeverity.WARNING,
        "error": RcaSeverity.ERROR,
        "critical": RcaSeverity.CRITICAL,
    }.get(severity.lower(), RcaSeverity.WARNING)


def _metric_unit(metric_name: str) -> RcaMeasurementUnit:
    if metric_name.endswith("_seconds"):
        return RcaMeasurementUnit.SECONDS
    return RcaMeasurementUnit.COUNT
