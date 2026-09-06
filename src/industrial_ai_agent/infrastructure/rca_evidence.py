"""Infrastructure adapters that project existing bounded evidence into RCA ports."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from math import isfinite
from typing import Protocol
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
    RcaEvidenceNotAuthorizedError,
    RcaEvidenceUnavailableError,
    RcaLlmGenerationObservation,
    RcaLlmTraceObservation,
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

_LANGFUSE_FIELDS = "core,basic,model,usage,metadata"
_LANGFUSE_ALLOWED_TYPES = {"AGENT", "GENERATION"}
_LANGFUSE_MAX_OBSERVATIONS = 50
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")


class LangfuseObservationsClient(Protocol):
    """Small Infrastructure-only view of the SDK's generated observations client."""

    def get_many(self, **kwargs: object) -> object:
        """Read one bounded page from Langfuse Observations API v2."""


class LangfuseRcaEvidenceAdapter:
    """Project one bounded Langfuse v2 response through a metadata-only allowlist."""

    def __init__(
        self,
        observations: LangfuseObservationsClient,
        *,
        max_observations: int = _LANGFUSE_MAX_OBSERVATIONS,
        timeout_seconds: int = 2,
    ) -> None:
        if not 1 <= max_observations <= _LANGFUSE_MAX_OBSERVATIONS:
            raise ValueError("Langfuse observation limit must be within the RCA bound")
        if timeout_seconds < 1:
            raise ValueError("Langfuse timeout must be positive")
        self._observations = observations
        self._max_observations = max_observations
        self._timeout_seconds = timeout_seconds

    def get_trace_llm_evidence(
        self,
        trace_id: str,
        *,
        from_time: datetime,
        to_time: datetime,
    ) -> RcaLlmTraceObservation:
        if from_time > to_time:
            raise RcaEvidenceMalformedError("Langfuse time window is invalid")
        try:
            response = self._observations.get_many(
                trace_id=trace_id,
                fields=_LANGFUSE_FIELDS,
                limit=self._max_observations,
                from_start_time=from_time,
                to_start_time=to_time,
                request_options={
                    "timeout_in_seconds": self._timeout_seconds,
                    "max_retries": 0,
                },
            )
        except PermissionError as error:
            raise RcaEvidenceNotAuthorizedError(
                "Langfuse evidence access was not authorized"
            ) from error
        except (OSError, TimeoutError) as error:
            raise RcaEvidenceUnavailableError(
                "Langfuse evidence is unavailable"
            ) from error
        except Exception as error:
            if _backend_status_code(error) in {401, 403}:
                raise RcaEvidenceNotAuthorizedError(
                    "Langfuse evidence access was not authorized"
                ) from error
            raise RcaEvidenceUnavailableError(
                "Langfuse evidence is unavailable"
            ) from error
        return _langfuse_trace_observation(response, trace_id)


def _langfuse_trace_observation(
    response: object, expected_trace_id: str
) -> RcaLlmTraceObservation:
    try:
        rows = tuple(response.data)
        meta = response.meta
        truncated = bool(getattr(meta, "cursor", None))
    except (AttributeError, TypeError) as error:
        raise RcaEvidenceMalformedError("Langfuse response is malformed") from error

    generations: list[RcaLlmGenerationObservation] = []
    trace_id_consistent = True
    malformed_generation = False
    for row in rows:
        row_type = getattr(row, "type", None)
        name = getattr(row, "name", None)
        if row_type not in _LANGFUSE_ALLOWED_TYPES:
            continue
        if (row_type, name) not in {("AGENT", "agent.run"), ("GENERATION", "llm.call")}:
            continue
        if getattr(row, "trace_id", None) != expected_trace_id:
            trace_id_consistent = False
            continue
        if row_type == "AGENT":
            continue
        try:
            generations.append(_langfuse_generation_observation(row))
        except (TypeError, ValueError):
            malformed_generation = True
    if malformed_generation and not generations:
        raise RcaEvidenceMalformedError("Langfuse generation data is malformed")
    return RcaLlmTraceObservation(
        trace_id_consistent=trace_id_consistent,
        generations=tuple(generations),
        truncated=truncated,
    )


def _langfuse_generation_observation(row: object) -> RcaLlmGenerationObservation:
    started_at = row.start_time
    ended_at = row.end_time
    if not isinstance(started_at, datetime) or not isinstance(ended_at, datetime):
        raise TypeError("Langfuse generation requires start and end times")
    duration_ms = (ended_at - started_at).total_seconds() * 1_000
    if not isfinite(duration_ms) or not 0 <= duration_ms <= 86_400_000:
        raise ValueError("Langfuse generation duration is invalid")
    metadata = getattr(row, "metadata", None)
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("Langfuse metadata must be an object")
    metadata = metadata or {}
    cost_status = metadata.get("cost_status")
    configured_cost = (
        _finite_nonnegative_float(metadata.get("attributes.cost.api_usd"))
        if cost_status == "configured_api_cost"
        else None
    )
    observed_cost = (
        _finite_nonnegative_float(getattr(row, "total_cost", None))
        if cost_status == "observed_run_cost"
        else None
    )
    return RcaLlmGenerationObservation(
        model_name=_safe_name(
            getattr(row, "provided_model_name", None)
            or metadata.get("attributes.model.name")
        ),
        provider=_safe_name(metadata.get("provider")),
        model_profile=_safe_name(metadata.get("model_profile")),
        status=_langfuse_status(metadata.get("success")),
        started_at=started_at,
        duration_ms=duration_ms,
        input_tokens=_usage_value(getattr(row, "usage_details", None), "input"),
        output_tokens=_usage_value(getattr(row, "usage_details", None), "output"),
        total_tokens=_usage_value(getattr(row, "usage_details", None), "total"),
        observed_cost_usd=observed_cost,
        configured_api_cost_usd=configured_cost,
    )


def _safe_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_NAME.fullmatch(value) is None:
        raise ValueError("Langfuse safe metadata value is invalid")
    return value


def _usage_value(value: object, key: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("Langfuse usage details must be an object")
    item = value.get(key)
    if item is None:
        return None
    if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 10**12:
        raise ValueError("Langfuse token usage is invalid")
    return item


def _finite_nonnegative_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("Langfuse numeric value is invalid")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0:
        raise ValueError("Langfuse numeric value is invalid")
    return normalized


def _langfuse_status(value: object) -> RcaOperationStatus:
    if value in (True, "true"):
        return RcaOperationStatus.OK
    if value in (False, "false"):
        return RcaOperationStatus.ERROR
    return RcaOperationStatus.UNSET


def _backend_status_code(error: Exception) -> int | None:
    try:
        value = error.status_code  # type: ignore[attr-defined]
    except AttributeError:
        return None
    return value if isinstance(value, int) else None


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
