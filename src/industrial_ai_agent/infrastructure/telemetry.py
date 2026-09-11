"""OpenTelemetry bootstrap and safe, infrastructure-only telemetry helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from opentelemetry import metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace.status import Status, StatusCode

TELEMETRY_SCOPE = "industrial_ai_agent.observability"
_MCP_TRACE_CONTEXT_PROPAGATOR = TraceContextTextMapPropagator()
_FORBIDDEN_ATTRIBUTE_PARTS = frozenset(
    {
        "authorization",
        "bearer",
        "chunk",
        "connection",
        "database_url",
        "document_text",
        "password",
        "prompt",
        "response_text",
        "secret",
        "sql.parameter",
        "tool_result",
    }
)
_ALLOWED_ATTRIBUTE_KEYS = frozenset(
    {
        "approval.decision",
        "data.classification",
        "embedding.model",
        "error.code",
        "error.stage",
        "error.type",
        "execution.zone",
        "cost.api_usd",
        "gen_ai.operation.name",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.usage.cost",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.total_tokens",
        "langfuse.observation.metadata.classification",
        "langfuse.observation.metadata.cost_status",
        "langfuse.observation.metadata.model_profile",
        "langfuse.observation.metadata.operation",
        "langfuse.observation.metadata.provider",
        "langfuse.observation.metadata.rca_focus",
        "langfuse.observation.metadata.run_id",
        "langfuse.observation.metadata.success",
        "langfuse.observation.metadata.usage_status",
        "langfuse.observation.model.name",
        "langfuse.observation.type",
        "mcp.operation",
        "mcp.server",
        "mcp.tool",
        "model.name",
        "model.provider",
        "model.profile",
        "operation.status",
        "operation.type",
        "recovery.outcome",
        "recovery.stage",
        "persistence.operation",
        "rca.focus",
        "retrieval.candidate_count",
        "retrieval.result_count",
        "retrieval.strategy",
        "reranker.model",
        "run.id",
        "run.profile",
        "verification.status",
        "telemetry.metadata_only",
        "telemetry.cost_status",
        "telemetry.usage_status",
        "token.input_count",
        "token.output_count",
        "token.total_count",
    }
)
_LANGFUSE_OBSERVATION_TYPES = {
    "agent.run": "agent",
    "llm.call": "generation",
}
_ACTIVE_RUN_ID: ContextVar[str | None] = ContextVar(
    "telemetry_active_run_id", default=None
)
_METRIC_ATTRIBUTE_KEYS = frozenset(
    {
        "approval.decision",
        "data.classification",
        "error.code",
        "error.stage",
        "execution.zone",
        "mcp.operation",
        "mcp.server",
        "mcp.tool",
        "model.profile",
        "operation.status",
        "operation.type",
        "recovery.outcome",
        "recovery.stage",
        "persistence.operation",
        "rca.focus",
        "retrieval.strategy",
        "run.profile",
        "verification.status",
    }
)
_ALLOWED_LOG_EVENTS = frozenset(
    {
        "agent.run.completed",
        "agent.run.failed",
        "mcp.server.completed",
        "mcp.server.failed",
        "recovery.action_attempted",
        "recovery.action_failed",
        "recovery.blocked",
        "recovery.prepared",
        "recovery.succeeded",
        "recovery.verification_failed",
    }
)


@dataclass(frozen=True, slots=True)
class TelemetryConfiguration:
    """Explicit configuration for optional local OTLP telemetry."""

    enabled: bool = False
    otlp_endpoint: str = "127.0.0.1:4317"
    service_name: str = "industrial-ai-agent"
    service_version: str = "0.1.0"
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "http://127.0.0.1:3001"
    langfuse_environment: str = "local"
    langfuse_release: str | None = None


class Telemetry:
    """Small safe facade around OTel SDK objects owned by Infrastructure."""

    def __init__(
        self,
        configuration: TelemetryConfiguration,
        *,
        tracer_provider: TracerProvider | None = None,
        meter_provider: MeterProvider | None = None,
        logger_provider: LoggerProvider | None = None,
        langfuse_client: object | None = None,
    ) -> None:
        self._configuration = configuration
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._logger_provider = logger_provider
        self._langfuse_client = langfuse_client
        self._tracer = (
            tracer_provider.get_tracer(TELEMETRY_SCOPE)
            if tracer_provider is not None
            else trace.get_tracer(TELEMETRY_SCOPE)
        )
        meter = (
            meter_provider.get_meter(TELEMETRY_SCOPE)
            if meter_provider is not None
            else metrics.get_meter(TELEMETRY_SCOPE)
        )
        self._agent_runs = meter.create_counter("agent_runs_total")
        self._agent_errors = meter.create_counter("agent_errors_total")
        self._mcp_calls = meter.create_counter("mcp_tool_calls_total")
        self._mcp_discovery = meter.create_counter("mcp_discovery_total")
        self._llm_calls = meter.create_counter("llm_calls_total")
        self._llm_input_tokens = meter.create_counter("llm_input_tokens_total")
        self._llm_output_tokens = meter.create_counter("llm_output_tokens_total")
        self._llm_total_tokens = meter.create_counter("llm_total_tokens_total")
        self._llm_tool_calls = meter.create_counter("llm_tool_calls_total")
        self._llm_tool_input_tokens = meter.create_counter(
            "llm_tool_input_tokens_total"
        )
        self._llm_tool_output_tokens = meter.create_counter(
            "llm_tool_output_tokens_total"
        )
        self._llm_tool_tokens = meter.create_counter("llm_tool_tokens_total")
        self._retrieval_calls = meter.create_counter("retrieval_calls_total")
        self._approvals = meter.create_counter("approval_total")
        self._recovery_lifecycle = meter.create_counter("recovery_lifecycle_total")
        self._persistence_operations = meter.create_counter(
            "persistence_operations_total"
        )
        self._agent_duration = meter.create_histogram("agent_run_duration_seconds")
        self._mcp_duration = meter.create_histogram("mcp_tool_duration_seconds")
        self._llm_duration = meter.create_histogram("llm_call_duration_seconds")
        self._persistence_duration = meter.create_histogram(
            "persistence_operation_duration_seconds"
        )
        self._logger = logging.getLogger("industrial_ai_agent.telemetry")

    @property
    def enabled(self) -> bool:
        return self._configuration.enabled

    @property
    def langfuse_enabled(self) -> bool:
        """Whether the optional Langfuse processor was configured successfully."""
        return self._langfuse_client is not None

    @property
    def tracer_provider(self) -> TracerProvider | None:
        return self._tracer_provider

    @property
    def meter_provider(self) -> MeterProvider | None:
        return self._meter_provider

    def log_error(self, *, event: str, run_id: str | None, error_code: str) -> None:
        """Emit a fixed, metadata-only error event correlated by the active span."""
        self._log(event=event, run_id=run_id, error_code=error_code, level="error")

    def log_event(self, *, event: str, run_id: str | None) -> None:
        """Emit a fixed, metadata-only operational event correlated by the active span."""
        self._log(event=event, run_id=run_id, error_code=None, level="info")

    def set_span_attributes(self, span: Span, attributes: Mapping[str, object]) -> None:
        """Add dynamic metadata only after applying the telemetry allowlist."""
        for key, value in self._span_attributes(
            getattr(span, "name", ""), attributes
        ).items():
            span.set_attribute(key, value)

    def set_current_span_attributes(self, attributes: Mapping[str, object]) -> None:
        """Add allowlisted metadata to the active span without exposing payloads."""
        self.set_span_attributes(trace.get_current_span(), attributes)

    def shutdown(self) -> None:
        """Flush optional telemetry before an API process exits; never raise to business code."""
        if self._langfuse_client is not None:
            for method_name in ("flush", "shutdown"):
                try:
                    method = getattr(self._langfuse_client, method_name)
                    method()
                except Exception:  # noqa: BLE001, S110 - telemetry must remain optional.
                    pass
        for provider in (
            self._logger_provider,
            self._meter_provider,
            self._tracer_provider,
        ):
            if provider is None:
                continue
            try:
                provider.force_flush()  # type: ignore[attr-defined]
                provider.shutdown()
            except Exception:  # noqa: BLE001, S110 - telemetry must remain optional.
                pass

    @contextmanager
    def span(
        self, name: str, attributes: Mapping[str, object] | None = None
    ) -> Iterator[Span]:
        """Create a span with allowlisted metadata and sanitized error state only."""
        if not self.enabled:
            yield trace.get_current_span()
            return
        effective_attributes = dict(attributes or {})
        inherited_run_id = _ACTIVE_RUN_ID.get()
        if inherited_run_id is not None:
            effective_attributes.setdefault("run.id", inherited_run_id)
        run_id = effective_attributes.get("run.id")
        run_id_token: Token[str | None] | None = None
        if isinstance(run_id, str):
            run_id_token = _ACTIVE_RUN_ID.set(run_id)
        with self._tracer.start_as_current_span(
            name,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            for key, value in self._span_attributes(name, effective_attributes).items():
                span.set_attribute(key, value)
            try:
                yield span
                span.set_attribute("operation.status", "success")
                self._set_langfuse_success(span, success=True)
            except BaseException as error:
                span.set_attribute("operation.status", "failure")
                self._set_langfuse_success(span, success=False)
                span.set_attribute("error.type", _telemetry_error_type(error))
                span.set_attribute("error.code", sanitized_error_code(error))
                error_stage = getattr(error, "error_stage", None)
                if isinstance(error_stage, str) and error_stage == "llm_provider":
                    span.set_attribute("error.stage", error_stage)
                span.set_status(Status(StatusCode.ERROR, sanitized_error_code(error)))
                raise
            finally:
                if run_id_token is not None:
                    _ACTIVE_RUN_ID.reset(run_id_token)

    def _span_attributes(
        self, name: str, attributes: Mapping[str, object]
    ) -> dict[str, bool | float | int | str]:
        safe = safe_attributes(attributes)
        if self.langfuse_enabled:
            safe.update(_langfuse_attributes(name, safe))
        return safe

    def _set_langfuse_success(self, span: Span, *, success: bool) -> None:
        if (
            self.langfuse_enabled
            and getattr(span, "name", "") in _LANGFUSE_OBSERVATION_TYPES
        ):
            span.set_attribute(
                "langfuse.observation.metadata.success", "true" if success else "false"
            )

    def _log(
        self,
        *,
        event: str,
        run_id: str | None,
        error_code: str | None,
        level: str,
    ) -> None:
        if not self.enabled or event not in _ALLOWED_LOG_EVENTS:
            return
        extra: dict[str, str] = {"event.name": event}
        if run_id is not None:
            extra["run.id"] = run_id
        if error_code is not None:
            extra["error.code"] = error_code
        getattr(self._logger, level)(event, extra=extra)

    def record_agent_run(
        self, *, status: str, duration_seconds: float, classification: str
    ) -> None:
        attributes = metric_attributes(
            {"operation.status": status, "data.classification": classification}
        )
        self._agent_runs.add(1, attributes)
        self._agent_duration.record(duration_seconds, attributes)
        if status != "success":
            self._agent_errors.add(1, attributes)

    def record_llm_call(
        self, *, attributes: Mapping[str, object], duration_seconds: float
    ) -> None:
        safe = metric_attributes(attributes)
        self._record_metric(self._llm_calls.add, 1, safe)
        self._record_metric(self._llm_duration.record, duration_seconds, safe)

    def record_llm_usage(
        self,
        *,
        attributes: Mapping[str, object],
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
    ) -> None:
        """Record valid provider-reported token counts without affecting execution."""
        safe = metric_attributes(attributes)
        for counter, value in (
            (self._llm_input_tokens, input_tokens),
            (self._llm_output_tokens, output_tokens),
            (self._llm_total_tokens, total_tokens),
        ):
            if _valid_token_count(value):
                self._record_metric(counter.add, value, safe)

    def record_llm_tool_usage(
        self,
        *,
        attributes: Mapping[str, object],
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
    ) -> None:
        """Record one bounded tool decision and its exact source LLM usage."""
        safe = metric_attributes(attributes)
        self._record_metric(self._llm_tool_calls.add, 1, safe)
        for counter, value in (
            (self._llm_tool_input_tokens, input_tokens),
            (self._llm_tool_output_tokens, output_tokens),
            (self._llm_tool_tokens, total_tokens),
        ):
            if _valid_token_count(value):
                self._record_metric(counter.add, value, safe)

    def record_mcp_call(
        self, *, attributes: Mapping[str, object], duration_seconds: float
    ) -> None:
        safe = metric_attributes(attributes)
        self._mcp_calls.add(1, safe)
        self._mcp_duration.record(duration_seconds, safe)

    def record_mcp_discovery(self, *, attributes: Mapping[str, object]) -> None:
        self._mcp_discovery.add(1, metric_attributes(attributes))

    def record_retrieval(self, *, attributes: Mapping[str, object]) -> None:
        self._retrieval_calls.add(1, metric_attributes(attributes))

    def record_approval(self, *, decision: str, classification: str) -> None:
        self._approvals.add(
            1,
            metric_attributes(
                {
                    "approval.decision": decision,
                    "data.classification": classification,
                }
            ),
        )

    def record_recovery_lifecycle(
        self,
        *,
        stage: str,
        outcome: str,
        verification_status: str,
        classification: str,
    ) -> None:
        """Record one fixed physical-recovery lifecycle signal without payload data."""
        attributes = metric_attributes(
            {
                "recovery.stage": stage,
                "recovery.outcome": outcome,
                "verification.status": verification_status,
                "data.classification": classification,
            }
        )
        self._recovery_lifecycle.add(1, attributes)
        self.log_event(event=f"recovery.{stage}", run_id=None)

    def record_persistence_operation(
        self, *, attributes: Mapping[str, object], duration_seconds: float
    ) -> None:
        safe = metric_attributes(attributes)
        self._persistence_operations.add(1, safe)
        self._persistence_duration.record(duration_seconds, safe)

    @staticmethod
    def _record_metric(
        recorder: object, value: float, attributes: Mapping[str, object]
    ) -> None:
        """Keep optional metric transport failures outside the request outcome."""
        try:
            recorder(value, attributes)  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - telemetry must never fail business code.
            return


def configure_telemetry(configuration: TelemetryConfiguration) -> Telemetry:
    """Build providers explicitly; disabled telemetry uses OTel's no-op default path."""
    if not configuration.enabled:
        return Telemetry(configuration)
    resource = Resource.create(
        {
            SERVICE_NAME: configuration.service_name,
            SERVICE_VERSION: configuration.service_version,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=configuration.otlp_endpoint,
                insecure=True,
                timeout=1,
            ),
            schedule_delay_millis=1_000,
            export_timeout_millis=1_000,
        )
    )
    langfuse_client = _configure_langfuse(configuration, tracer_provider)
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=configuration.otlp_endpoint,
                    insecure=True,
                ),
                export_interval_millis=5_000,
            )
        ],
    )
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=configuration.otlp_endpoint,
                insecure=True,
                timeout=1,
            ),
            schedule_delay_millis=1_000,
            export_timeout_millis=1_000,
        )
    )
    telemetry_logger = logging.getLogger("industrial_ai_agent.telemetry")
    telemetry_logger.handlers = [LoggingHandler(logger_provider=logger_provider)]
    telemetry_logger.propagate = False
    telemetry_logger.setLevel(logging.INFO)
    # FastAPI and other maintained instrumentation obtain providers from OTel globals.
    # This explicit Infrastructure bootstrap remains the only installation point.
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    return Telemetry(
        configuration,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        langfuse_client=langfuse_client,
    )


def _configure_langfuse(
    configuration: TelemetryConfiguration, tracer_provider: TracerProvider
) -> object | None:
    """Attach Langfuse to the existing provider with a narrow span export policy."""
    if (
        not configuration.langfuse_enabled
        or not configuration.langfuse_public_key
        or not configuration.langfuse_secret_key
    ):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=configuration.langfuse_public_key,
            secret_key=configuration.langfuse_secret_key,
            base_url=configuration.langfuse_base_url,
            environment=configuration.langfuse_environment,
            release=configuration.langfuse_release,
            tracer_provider=tracer_provider,
            should_export_span=_should_export_to_langfuse,
            additional_headers={"x-langfuse-ingestion-version": "4"},
        )
    except Exception:  # noqa: BLE001 - observability must fail open.
        return None


def instrument_fastapi(app: object, telemetry: Telemetry) -> None:
    """Install maintained FastAPI instrumentation only when telemetry is enabled."""
    if not telemetry.enabled or telemetry.tracer_provider is None:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        excluded_urls="health",
    )


def instrument_mcp_http_client(
    http_client: object, telemetry: Telemetry | None
) -> None:
    """Inject W3C context through the public request-hook API of MCP's HTTP client."""
    if telemetry is None or not telemetry.enabled or telemetry.tracer_provider is None:
        return
    try:
        event_hooks = http_client.event_hooks  # type: ignore[attr-defined]
        event_hooks.setdefault("request", []).append(_inject_mcp_trace_context)
    except Exception:  # noqa: BLE001 - telemetry must not block MCP calls.
        return


def instrument_mcp_http_app(app: object, telemetry: Telemetry) -> None:
    """Add W3C Trace Context-only ASGI tracing at the MCP HTTP boundary."""
    if not telemetry.enabled or telemetry.tracer_provider is None:
        return
    try:
        from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

        # The public ASGI instrumentation extracts from OTel's global propagator.
        # MCP deliberately allows only W3C trace context, never baggage.
        propagate.set_global_textmap(_MCP_TRACE_CONTEXT_PROPAGATOR)
        app.add_middleware(  # type: ignore[attr-defined]
            OpenTelemetryMiddleware,
            tracer_provider=telemetry.tracer_provider,
            meter_provider=telemetry.meter_provider,
        )
    except Exception:  # noqa: BLE001 - telemetry must not block MCP startup.
        return


def run_instrumented_mcp_http_server(
    server: object,
    *,
    host: str,
    port: int,
    streamable_http_path: str,
    telemetry: Telemetry,
) -> None:
    """Run the public MCP Starlette app with optional ASGI trace extraction."""
    import uvicorn

    app = server.streamable_http_app(  # type: ignore[attr-defined]
        host=host,
        streamable_http_path=streamable_http_path,
    )
    instrument_mcp_http_app(app, telemetry)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        telemetry.shutdown()


async def _inject_mcp_trace_context(request: object) -> None:
    """Replace caller-supplied context with active W3C trace context only."""
    try:
        headers = request.headers  # type: ignore[attr-defined]
        for header in ("traceparent", "tracestate", "baggage"):
            headers.pop(header, None)
        _MCP_TRACE_CONTEXT_PROPAGATOR.inject(headers)
    except Exception:  # noqa: BLE001 - telemetry must not block MCP calls.
        return


def safe_attributes(
    attributes: Mapping[str, object],
) -> dict[str, bool | float | int | str]:
    """Drop unknown/sensitive keys rather than risking a telemetry data leak."""
    return {
        key: normalized
        for key, value in attributes.items()
        if key in _ALLOWED_ATTRIBUTE_KEYS
        and not _contains_forbidden_part(key)
        and (normalized := _normalize_attribute_value(value)) is not None
    }


def metric_attributes(
    attributes: Mapping[str, object],
) -> dict[str, bool | float | int | str]:
    """Restrict metrics to bounded dimensions; identifiers never become labels."""
    return {
        key: value
        for key, value in safe_attributes(attributes).items()
        if key in _METRIC_ATTRIBUTE_KEYS
    }


def sanitized_error_code(error: BaseException) -> str:
    """Use an explicit machine code when safe, otherwise only the exception type."""
    value = getattr(error, "code", None)
    if isinstance(value, str) and value.isidentifier() and len(value) <= 80:
        return value
    return type(error).__name__


def _telemetry_error_type(error: BaseException) -> str:
    """Keep provider type observability bounded without accepting arbitrary text."""
    provider_error_type = getattr(error, "provider_error_type", None)
    if isinstance(provider_error_type, str) and provider_error_type in {
        "APIConnectionError",
        "APIStatusError",
        "RateLimitError",
    }:
        return provider_error_type
    return type(error).__name__


def _contains_forbidden_part(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _FORBIDDEN_ATTRIBUTE_PARTS)


def _normalize_attribute_value(value: object) -> bool | float | int | str | None:
    if isinstance(value, bool | float | int):
        return value
    if isinstance(value, str) and len(value) <= 160 and "\n" not in value:
        return value
    return None


def _valid_token_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _langfuse_attributes(
    name: str, attributes: Mapping[str, bool | float | int | str]
) -> dict[str, bool | float | int | str]:
    """Map the metadata allowlist onto Langfuse's OTel ingestion conventions."""
    observation_type = _LANGFUSE_OBSERVATION_TYPES.get(name)
    if observation_type is None:
        return {}
    mapped: dict[str, bool | float | int | str] = {
        "langfuse.observation.type": observation_type,
    }
    metadata_keys = {
        "run.id": "run_id",
        "data.classification": "classification",
        "model.profile": "model_profile",
        "operation.type": "operation",
        "rca.focus": "rca_focus",
        "model.provider": "provider",
        "operation.status": "success",
        "telemetry.usage_status": "usage_status",
        "telemetry.cost_status": "cost_status",
    }
    for source, destination in metadata_keys.items():
        value = attributes.get(source)
        if value is None:
            continue
        if source == "operation.status":
            value = "true" if value == "success" else "false"
        mapped[f"langfuse.observation.metadata.{destination}"] = str(value)

    if name == "llm.call":
        model_name = attributes.get("model.name")
        provider = attributes.get("model.provider")
        if model_name is not None:
            mapped["langfuse.observation.model.name"] = model_name
            mapped["gen_ai.request.model"] = model_name
        if provider is not None:
            mapped["gen_ai.provider.name"] = provider
        token_mappings = {
            "token.input_count": "gen_ai.usage.input_tokens",
            "token.output_count": "gen_ai.usage.output_tokens",
            "token.total_count": "gen_ai.usage.total_tokens",
            "cost.api_usd": "gen_ai.usage.cost",
        }
        for source, destination in token_mappings.items():
            value = attributes.get(source)
            if value is not None:
                mapped[destination] = value
        mapped["gen_ai.operation.name"] = "chat"
    return mapped


def _should_export_to_langfuse(span: object) -> bool:
    """Export only project-owned agent and generation observations to Langfuse."""
    # Langfuse evaluates this predicate when the span starts, before attributes are
    # attached. The closed span-name allowlist is therefore the enforcement point.
    return getattr(span, "name", "") in _LANGFUSE_OBSERVATION_TYPES


def timed() -> tuple[float, Any]:
    """Return a monotonic timer start and a local elapsed-time closure."""
    start = perf_counter()
    return start, lambda: perf_counter() - start
