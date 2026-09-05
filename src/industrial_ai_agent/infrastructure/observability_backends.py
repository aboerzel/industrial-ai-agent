"""Bounded, read-only adapters for the local observability backends."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from industrial_ai_agent.infrastructure.telemetry import safe_attributes

KNOWN_OBSERVABILITY_SERVICES = frozenset(
    {
        "industrial-ai-agent",
        "factory-mcp",
        "knowledge-mcp",
        "observability-mcp",
        "runtime-mcp",
    }
)
MAX_TRACE_SPANS = 200
MAX_LOG_EVENTS = 100
MAX_METRIC_POINTS = 60
MAX_LOOKBACK = timedelta(hours=48)
TRACE_CONTEXT_PADDING = timedelta(minutes=5)
MAX_TRACE_CONTEXT_WINDOW = timedelta(minutes=30)
SERVICE_HEALTH_WINDOWS = {"5m": timedelta(minutes=5), "15m": timedelta(minutes=15), "1h": timedelta(hours=1)}
_OWNED_FAILURE_OPERATIONS = frozenset(
    {
        "agent.run",
        "model.routing",
        "llm.call",
        "mcp.discovery",
        "mcp.tool",
        "retrieval.search",
        "approval.resume",
        "maintenance_ticket.create",
        "persistence.run_store",
    }
)


class ObservabilityBackendError(RuntimeError):
    """Base error for a failed bounded observability backend operation."""


class ObservabilityBackendUnavailable(ObservabilityBackendError):
    """The backend could not be reached or returned a server failure."""


class ObservabilityNotFoundError(ObservabilityBackendError):
    """A requested trace does not exist within the bounded retention window."""


class ObservabilityMalformedResponse(ObservabilityBackendError):
    """A backend response did not match the stable response subset we consume."""


class InvalidObservabilityIdentifier(ValueError):
    """A run or trace identifier is not in the accepted bounded format."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TraceSpan(_StrictModel):
    span_id: str
    parent_span_id: str | None
    operation_name: str
    service_name: str
    start_time: datetime
    duration_ms: float = Field(ge=0)
    status: Literal["ok", "error", "unset"]
    attributes: dict[str, bool | float | int | str]
    error_type: str | None = None
    error_code: str | None = None


class RunTrace(_StrictModel):
    run_id: str | None
    trace_id: str
    duration_ms: float = Field(ge=0)
    status: Literal["ok", "error", "unset"]
    participating_services: tuple[str, ...]
    spans: tuple[TraceSpan, ...]
    truncated: bool = False


class TraceLogEvent(_StrictModel):
    timestamp: datetime
    service_name: str
    event_name: str
    severity: str
    trace_id: str
    span_id: str | None = None
    run_id: str | None = None
    error_code: str | None = None


class MetricSeries(_StrictModel):
    name: str
    points: tuple[tuple[datetime, float], ...]


class MetricContext(_StrictModel):
    start_time: datetime
    end_time: datetime
    source: Literal["trace_correlated_window", "service_health_window"]
    series: tuple[MetricSeries, ...]


@dataclass(frozen=True, slots=True)
class BackendConfiguration:
    tempo_url: str = "http://127.0.0.1:3200"
    loki_url: str = "http://127.0.0.1:3100"
    prometheus_url: str = "http://127.0.0.1:9090"
    timeout_seconds: float = 2.0


class TempoAdapter:
    """Use only Tempo's stable trace-by-ID and bounded run lookup endpoints."""

    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=2.0)

    def get_run_trace(self, run_id: str) -> RunTrace:
        normalized_run_id = _validate_run_id(run_id)
        now = datetime.now(UTC)
        response = _get_json(
            self._client,
            f"{self._base_url}/api/search",
            params={
                "q": f'{{ span.run.id = "{normalized_run_id}" }}',
                "start": str(int((now - MAX_LOOKBACK).timestamp())),
                "end": str(int(now.timestamp())),
                "limit": "1",
                "spss": "1",
            },
            not_found_is_empty=True,
        )
        traces = response.get("traces") if isinstance(response, Mapping) else None
        if not isinstance(traces, list):
            raise ObservabilityMalformedResponse("Tempo search response is malformed")
        if not traces or not isinstance(traces[0], Mapping):
            raise ObservabilityNotFoundError("Run trace was not found")
        trace_id = traces[0].get("traceID")
        if not isinstance(trace_id, str):
            raise ObservabilityMalformedResponse("Tempo search result has no trace ID")
        trace = self.get_trace(trace_id)
        return trace.model_copy(update={"run_id": normalized_run_id})

    def get_trace(self, trace_id: str) -> RunTrace:
        normalized_trace_id = _validate_trace_id(trace_id)
        response = _get_json(
            self._client,
            f"{self._base_url}/api/v2/traces/{normalized_trace_id}",
        )
        trace = response.get("trace") if isinstance(response, Mapping) else None
        if not isinstance(trace, Mapping):
            raise ObservabilityMalformedResponse("Tempo trace response is malformed")
        return _parse_tempo_trace(trace, normalized_trace_id)


class LokiAdapter:
    """Read only metadata-only log events correlated by one validated trace ID."""

    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=2.0)

    def get_trace_logs(
        self,
        trace_id: str,
        *,
        start_time: datetime,
        end_time: datetime,
        service_name: str | None = None,
    ) -> tuple[TraceLogEvent, ...]:
        normalized_trace_id = _validate_trace_id(trace_id)
        normalized_service = _validate_service_name(service_name)
        start_time, end_time = _bounded_window(start_time, end_time)
        selector = f'{{trace_id="{normalized_trace_id}"'
        if normalized_service is not None:
            selector += f',service_name="{normalized_service}"'
        selector += "}"
        response = _get_json(
            self._client,
            f"{self._base_url}/loki/api/v1/query_range",
            params={
                "query": selector,
                "start": str(_unix_nanos(start_time)),
                "end": str(_unix_nanos(end_time)),
                "limit": str(MAX_LOG_EVENTS),
                "direction": "forward",
            },
        )
        data = response.get("data") if isinstance(response, Mapping) else None
        streams = data.get("result") if isinstance(data, Mapping) else None
        if not isinstance(streams, list):
            raise ObservabilityMalformedResponse("Loki response is malformed")
        events: list[TraceLogEvent] = []
        for stream in streams:
            if not isinstance(stream, Mapping):
                raise ObservabilityMalformedResponse("Loki stream is malformed")
            labels = stream.get("stream")
            values = stream.get("values")
            if not isinstance(labels, Mapping) or not isinstance(values, list):
                raise ObservabilityMalformedResponse("Loki stream fields are malformed")
            for value in values:
                if len(events) >= MAX_LOG_EVENTS:
                    break
                if not isinstance(value, list | tuple) or not value or not isinstance(value[0], str):
                    raise ObservabilityMalformedResponse("Loki event is malformed")
                event = _safe_log_event(labels, value[0], normalized_trace_id)
                if event is not None:
                    events.append(event)
        return tuple(sorted(events, key=lambda item: item.timestamp))


class PrometheusAdapter:
    """Construct fixed PromQL internally; public callers never supply query text."""

    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=2.0)

    def trace_metric_context(self, trace: RunTrace) -> MetricContext:
        spans = trace.spans
        if not spans:
            raise ObservabilityMalformedResponse("Trace contains no spans")
        start = min(span.start_time for span in spans) - TRACE_CONTEXT_PADDING
        end = max(
            span.start_time + timedelta(milliseconds=span.duration_ms) for span in spans
        ) + TRACE_CONTEXT_PADDING
        if end - start > MAX_TRACE_CONTEXT_WINDOW:
            end = start + MAX_TRACE_CONTEXT_WINDOW
        return self._metric_context(
            start_time=start,
            end_time=end,
            source="trace_correlated_window",
            service_name=None,
        )

    def service_health(self, service_name: str, time_window: str) -> MetricContext:
        service = _validate_service_name(service_name)
        assert service is not None
        try:
            window = SERVICE_HEALTH_WINDOWS[time_window]
        except KeyError as error:
            raise InvalidObservabilityIdentifier("Unsupported service health window") from error
        end = datetime.now(UTC)
        return self._metric_context(
            start_time=end - window,
            end_time=end,
            source="service_health_window",
            service_name=service,
        )

    def _metric_context(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        source: Literal["trace_correlated_window", "service_health_window"],
        service_name: str | None,
    ) -> MetricContext:
        start_time, end_time = _bounded_window(start_time, end_time)
        selector = f'{{service_name="{service_name}"}}' if service_name else ""
        window = _prometheus_duration(end_time - start_time)
        queries = {
            "run_count": f"sum(increase(agent_runs_total{selector}[{window}]))",
            "error_count": f"sum(increase(agent_errors_total{selector}[{window}]))",
            "mcp_discovery_count": f"sum(increase(mcp_discovery_total{selector}[{window}]))",
            "mcp_tool_call_count": f"sum(increase(mcp_tool_calls_total{selector}[{window}]))",
            "llm_call_count": f"sum(increase(llm_calls_total{selector}[{window}]))",
            "retrieval_call_count": f"sum(increase(retrieval_calls_total{selector}[{window}]))",
            "mcp_latency_p95_seconds": (
                "histogram_quantile(0.95, sum by (le) "
                f"(rate(mcp_tool_duration_seconds_bucket{selector}[{window}])))"
            ),
        }
        return MetricContext(
            start_time=start_time,
            end_time=end_time,
            source=source,
            series=tuple(
                MetricSeries(name=name, points=self._query_range(query, start_time, end_time))
                for name, query in queries.items()
            ),
        )

    def _query_range(
        self, query: str, start_time: datetime, end_time: datetime
    ) -> tuple[tuple[datetime, float], ...]:
        seconds = max(1, int((end_time - start_time).total_seconds()))
        step = max(1, (seconds + MAX_METRIC_POINTS - 1) // MAX_METRIC_POINTS)
        response = _get_json(
            self._client,
            f"{self._base_url}/api/v1/query_range",
            params={
                "query": query,
                "start": _rfc3339(start_time),
                "end": _rfc3339(end_time),
                "step": str(step),
            },
        )
        data = response.get("data") if isinstance(response, Mapping) else None
        result = data.get("result") if isinstance(data, Mapping) else None
        if not isinstance(result, list):
            raise ObservabilityMalformedResponse("Prometheus response is malformed")
        points: list[tuple[datetime, float]] = []
        for series in result:
            if not isinstance(series, Mapping):
                raise ObservabilityMalformedResponse("Prometheus series is malformed")
            values = series.get("values")
            if not isinstance(values, list):
                raise ObservabilityMalformedResponse("Prometheus values are malformed")
            for point in values:
                if len(points) >= MAX_METRIC_POINTS:
                    break
                if not isinstance(point, list | tuple) or len(point) != 2:
                    raise ObservabilityMalformedResponse("Prometheus point is malformed")
                timestamp, value = point
                try:
                    converted_timestamp = datetime.fromtimestamp(float(timestamp), UTC)
                    converted_value = float(value)
                except (TypeError, ValueError, OverflowError) as error:
                    raise ObservabilityMalformedResponse("Prometheus point value is malformed") from error
                points.append((converted_timestamp, converted_value))
        return tuple(sorted(points, key=lambda point: point[0]))


class ObservabilityEvidenceService:
    """Deterministically aggregate bounded backend evidence; it performs no RCA reasoning."""

    def __init__(
        self,
        *,
        tempo: TempoAdapter,
        loki: LokiAdapter,
        prometheus: PrometheusAdapter,
    ) -> None:
        self._tempo = tempo
        self._loki = loki
        self._prometheus = prometheus

    def get_run_trace(self, run_id: str) -> RunTrace:
        return self._tempo.get_run_trace(run_id)

    def get_trace_logs(
        self, trace_id: str, service_name: str | None = None
    ) -> tuple[TraceLogEvent, ...]:
        trace = self._tempo.get_trace(trace_id)
        return self._logs_for_trace(trace, service_name)

    def get_run_metrics(self, identifier: str) -> MetricContext:
        trace = self._trace_from_run_or_trace(identifier)
        return self._prometheus.trace_metric_context(trace)

    def get_service_health(self, service_name: str, time_window: str) -> MetricContext:
        return self._prometheus.service_health(service_name, time_window)

    def investigate_run(self, run_id: str) -> dict[str, object]:
        trace = self.get_run_trace(run_id)
        failure = next(
            (
                span
                for span in trace.spans
                if span.status == "error"
                and span.operation_name in _OWNED_FAILURE_OPERATIONS
            ),
            next((span for span in trace.spans if span.status == "error"), None),
        )
        logs = self._logs_for_trace(trace, failure.service_name if failure else None)
        metrics = self._prometheus.trace_metric_context(trace)
        evidence = []
        if failure is not None:
            evidence.append("An error span identifies the failure location.")
        else:
            evidence.append("No error span was recorded in the retrieved trace.")
        if logs:
            evidence.append("Metadata-only correlated log events are available.")
        else:
            evidence.append("No correlated metadata-only Loki events were returned.")
        return {
            "run_id": trace.run_id,
            "trace_id": trace.trace_id,
            "status": trace.status,
            "failure_stage": failure.operation_name if failure else None,
            "failing_service": failure.service_name if failure else None,
            "failing_operation": failure.operation_name if failure else None,
            "error_code": failure.error_code if failure else None,
            "timeline": [span.model_dump(mode="json") for span in trace.spans],
            "correlated_logs": [event.model_dump(mode="json") for event in logs],
            "metric_context": metrics.model_dump(mode="json"),
            "evidence": evidence,
            "limitations": [
                "This is deterministic evidence aggregation, not a root-cause conclusion.",
                "Prometheus metrics are trace-correlated time-window aggregates; run and trace IDs are not metric labels.",
                "Sanitized telemetry may identify a failure location without proving an underlying cause.",
            ],
        }

    def _trace_from_run_or_trace(self, identifier: str) -> RunTrace:
        try:
            return self._tempo.get_run_trace(identifier)
        except InvalidObservabilityIdentifier:
            return self._tempo.get_trace(identifier)

    def _logs_for_trace(
        self, trace: RunTrace, service_name: str | None
    ) -> tuple[TraceLogEvent, ...]:
        spans = trace.spans
        if not spans:
            return ()
        start = min(span.start_time for span in spans) - TRACE_CONTEXT_PADDING
        end = max(
            span.start_time + timedelta(milliseconds=span.duration_ms) for span in spans
        ) + TRACE_CONTEXT_PADDING
        return self._loki.get_trace_logs(
            trace.trace_id,
            start_time=start,
            end_time=end,
            service_name=service_name,
        )


def _get_json(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    not_found_is_empty: bool = False,
) -> Mapping[str, object]:
    try:
        response = client.get(url, params=params)
    except httpx.RequestError as error:
        raise ObservabilityBackendUnavailable("Observability backend is unavailable") from error
    if response.status_code == 404 and not not_found_is_empty:
        raise ObservabilityNotFoundError("Observability data was not found")
    if response.status_code >= 500:
        raise ObservabilityBackendUnavailable("Observability backend is unavailable")
    if response.status_code >= 400:
        raise ObservabilityMalformedResponse("Observability backend rejected bounded query")
    try:
        payload = response.json()
    except ValueError as error:
        raise ObservabilityMalformedResponse("Observability backend returned invalid JSON") from error
    if not isinstance(payload, Mapping):
        raise ObservabilityMalformedResponse("Observability backend returned invalid JSON")
    if payload.get("status") == "error":
        raise ObservabilityMalformedResponse("Observability backend returned an error")
    return payload


def _parse_tempo_trace(trace: Mapping[str, object], trace_id: str) -> RunTrace:
    resource_spans = trace.get("resourceSpans")
    if not isinstance(resource_spans, list):
        raise ObservabilityMalformedResponse("Tempo trace resource spans are malformed")
    spans: list[TraceSpan] = []
    for resource_span in resource_spans:
        if not isinstance(resource_span, Mapping):
            raise ObservabilityMalformedResponse("Tempo resource span is malformed")
        service_name = _tempo_service_name(resource_span)
        scope_spans = resource_span.get("scopeSpans")
        if not isinstance(scope_spans, list):
            raise ObservabilityMalformedResponse("Tempo scope spans are malformed")
        for scope_span in scope_spans:
            if not isinstance(scope_span, Mapping) or not isinstance(scope_span.get("spans"), list):
                raise ObservabilityMalformedResponse("Tempo scope span is malformed")
            for raw_span in scope_span["spans"]:
                if not isinstance(raw_span, Mapping):
                    raise ObservabilityMalformedResponse("Tempo span is malformed")
                spans.append(_parse_tempo_span(raw_span, service_name))
    if not spans:
        raise ObservabilityNotFoundError("Trace contains no spans")
    ordered = _parent_first_order(spans)
    retained = tuple(ordered[:MAX_TRACE_SPANS])
    start = min(span.start_time for span in retained)
    end = max(span.start_time + timedelta(milliseconds=span.duration_ms) for span in retained)
    statuses = {span.status for span in retained}
    status: Literal["ok", "error", "unset"] = "error" if "error" in statuses else "ok" if "ok" in statuses else "unset"
    return RunTrace(
        run_id=None,
        trace_id=trace_id,
        duration_ms=(end - start).total_seconds() * 1000,
        status=status,
        participating_services=tuple(sorted({span.service_name for span in retained})),
        spans=retained,
        truncated=len(ordered) > MAX_TRACE_SPANS,
    )


def _parse_tempo_span(raw_span: Mapping[str, object], service_name: str) -> TraceSpan:
    name = raw_span.get("name")
    span_id = raw_span.get("spanId")
    start_nanos = raw_span.get("startTimeUnixNano")
    end_nanos = raw_span.get("endTimeUnixNano")
    if not all(isinstance(value, str) and value for value in (name, span_id, start_nanos, end_nanos)):
        raise ObservabilityMalformedResponse("Tempo span fields are malformed")
    try:
        start = datetime.fromtimestamp(int(start_nanos) / 1_000_000_000, UTC)
        duration_ms = max(0, (int(end_nanos) - int(start_nanos)) / 1_000_000)
    except (ValueError, OverflowError) as error:
        raise ObservabilityMalformedResponse("Tempo span timing is malformed") from error
    attributes = _tempo_attributes(raw_span.get("attributes"))
    parent = raw_span.get("parentSpanId")
    parent_id = _base64_identifier(parent) if isinstance(parent, str) and parent else None
    error_code = attributes.get("error.code")
    error_type = attributes.get("error.type")
    raw_status = raw_span.get("status")
    status_code = raw_status.get("code") if isinstance(raw_status, Mapping) else None
    status: Literal["ok", "error", "unset"] = "error" if status_code in {2, "STATUS_CODE_ERROR", "ERROR"} or attributes.get("operation.status") == "failure" else "ok" if attributes.get("operation.status") == "success" else "unset"
    return TraceSpan(
        span_id=_base64_identifier(span_id),
        parent_span_id=parent_id,
        operation_name=name,
        service_name=service_name,
        start_time=start,
        duration_ms=duration_ms,
        status=status,
        attributes=attributes,
        error_type=error_type if isinstance(error_type, str) else None,
        error_code=error_code if isinstance(error_code, str) else None,
    )


def _tempo_attributes(value: object) -> dict[str, bool | float | int | str]:
    if not isinstance(value, list):
        return {}
    raw: dict[str, object] = {}
    for attribute in value:
        if not isinstance(attribute, Mapping):
            continue
        key = attribute.get("key")
        attribute_value = attribute.get("value")
        if isinstance(key, str):
            decoded = _otlp_value(attribute_value)
            if decoded is not None:
                raw[key] = decoded
    return safe_attributes(raw)


def _otlp_value(value: object) -> bool | float | int | str | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        candidate = value.get(key)
        if isinstance(candidate, bool | int | float | str):
            return candidate
    return None


def _tempo_service_name(resource_span: Mapping[str, object]) -> str:
    resource = resource_span.get("resource")
    attributes = resource.get("attributes") if isinstance(resource, Mapping) else None
    if not isinstance(attributes, list):
        raise ObservabilityMalformedResponse("Tempo resource attributes are malformed")
    for attribute in attributes:
        if isinstance(attribute, Mapping) and attribute.get("key") == "service.name":
            value = _otlp_value(attribute.get("value"))
            if isinstance(value, str) and value in KNOWN_OBSERVABILITY_SERVICES:
                return value
    raise ObservabilityMalformedResponse("Tempo span has no known service name")


def _parent_first_order(spans: Iterable[TraceSpan]) -> list[TraceSpan]:
    pending = sorted(spans, key=lambda span: (span.start_time, span.span_id))
    emitted: list[TraceSpan] = []
    emitted_ids: set[str] = set()
    while pending:
        ready = [span for span in pending if span.parent_span_id is None or span.parent_span_id in emitted_ids]
        if not ready:
            ready = [pending[0]]
        for span in ready:
            pending.remove(span)
            emitted.append(span)
            emitted_ids.add(span.span_id)
    return emitted


def _safe_log_event(
    labels: Mapping[str, object], timestamp_nanos: str, trace_id: str
) -> TraceLogEvent | None:
    event_name = labels.get("event_name")
    service_name = labels.get("service_name")
    label_trace_id = labels.get("trace_id")
    if not isinstance(event_name, str) or event_name not in {
        "agent.run.completed", "agent.run.failed", "mcp.server.completed", "mcp.server.failed"
    }:
        return None
    if not isinstance(service_name, str) or service_name not in KNOWN_OBSERVABILITY_SERVICES:
        return None
    if label_trace_id != trace_id:
        return None
    try:
        timestamp = datetime.fromtimestamp(int(timestamp_nanos) / 1_000_000_000, UTC)
    except (ValueError, OverflowError) as error:
        raise ObservabilityMalformedResponse("Loki timestamp is malformed") from error
    return TraceLogEvent(
        timestamp=timestamp,
        service_name=service_name,
        event_name=event_name,
        severity=_safe_string(labels.get("severity_text"), default="UNSET"),
        trace_id=trace_id,
        span_id=_safe_hex_identifier(labels.get("span_id")),
        run_id=_safe_uuid(labels.get("run_id") or labels.get("run.id")),
        error_code=_safe_error_code(labels.get("error_code") or labels.get("error.code")),
    )


def _validate_run_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError) as error:
        raise InvalidObservabilityIdentifier("Invalid run ID") from error


def _validate_trace_id(value: str) -> str:
    if not isinstance(value, str) or len(value) != 32:
        raise InvalidObservabilityIdentifier("Invalid trace ID")
    try:
        int(value, 16)
    except ValueError as error:
        raise InvalidObservabilityIdentifier("Invalid trace ID") from error
    return value.lower()


def _validate_service_name(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in KNOWN_OBSERVABILITY_SERVICES:
        raise InvalidObservabilityIdentifier("Unknown observability service")
    return value


def _bounded_window(start_time: datetime, end_time: datetime) -> tuple[datetime, datetime]:
    if start_time.tzinfo is None or end_time.tzinfo is None or end_time <= start_time:
        raise InvalidObservabilityIdentifier("Invalid observability time window")
    if end_time - start_time > MAX_LOOKBACK:
        raise InvalidObservabilityIdentifier("Observability time window exceeds the maximum")
    return start_time.astimezone(UTC), end_time.astimezone(UTC)


def _base64_identifier(value: str) -> str:
    try:
        return base64.b64decode(value, validate=True).hex()
    except (binascii.Error, ValueError) as error:
        raise ObservabilityMalformedResponse("Tempo identifier is malformed") from error


def _safe_hex_identifier(value: object) -> str | None:
    if isinstance(value, str) and 1 <= len(value) <= 32:
        try:
            int(value, 16)
        except ValueError:
            return None
        return value.lower()
    return None


def _safe_uuid(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _safe_error_code(value: object) -> str | None:
    if isinstance(value, str) and value.isidentifier() and len(value) <= 80:
        return value
    return None


def _safe_string(value: object, *, default: str) -> str:
    return value if isinstance(value, str) and len(value) <= 80 else default


def _unix_nanos(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _prometheus_duration(value: timedelta) -> str:
    return f"{max(1, int(value.total_seconds()))}s"
