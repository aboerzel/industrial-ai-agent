from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.types import CallToolResult, Tool
from opentelemetry import baggage, propagate, trace
from opentelemetry.context import attach, detach
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from industrial_ai_agent.agent.llm import LLMProviderError, LLMProviderErrorCode
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    _create_langchain_tool,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    configure_telemetry,
    instrument_mcp_http_app,
    instrument_mcp_http_client,
    metric_attributes,
    safe_attributes,
)


def test_disabled_bootstrap_is_safe_without_a_collector() -> None:
    telemetry = configure_telemetry(TelemetryConfiguration(enabled=False))

    with telemetry.span("agent.run", {"run.id": "run-1"}):
        pass

    assert telemetry.enabled is False


def test_unreachable_collector_does_not_break_local_span_execution() -> None:
    telemetry = configure_telemetry(
        TelemetryConfiguration(enabled=True, otlp_endpoint="127.0.0.1:1")
    )

    with telemetry.span("mcp.tool", {"mcp.tool": "get_machine_status"}):
        pass

    telemetry.shutdown()


def test_span_keeps_run_and_model_metadata_without_sensitive_attributes() -> None:
    telemetry, exporter = _recording_telemetry()

    with telemetry.span(
        "llm.call",
        {
            "run.id": "run-1",
            "model.profile": "local_quality",
            "model.name": "qwen3.5:9b",
            "data.classification": "CONFIDENTIAL",
            "token.input_count": 42,
            "prompt": "must never leave the process",
            "authorization": "Bearer local-secret",
        },
    ):
        pass

    span = exporter.get_finished_spans()[0]
    assert span.attributes["run.id"] == "run-1"
    assert span.attributes["model.profile"] == "local_quality"
    assert span.attributes["token.input_count"] == 42
    assert "prompt" not in span.attributes
    assert "authorization" not in span.attributes


def test_error_span_has_sanitized_error_metadata() -> None:
    telemetry, exporter = _recording_telemetry()

    with (
        pytest.raises(RuntimeError),
        telemetry.span("mcp.tool", {"mcp.tool": "get_machine_status"}),
    ):
        raise RuntimeError("Bearer secret must not be recorded")

    span = exporter.get_finished_spans()[0]
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.attributes["error.code"] == "RuntimeError"
    assert "Bearer" not in str(span.attributes)
    assert span.events == ()


def test_provider_limit_span_uses_bounded_provider_attributes() -> None:
    telemetry, exporter = _recording_telemetry()

    with (
        pytest.raises(LLMProviderError),
        telemetry.span("llm.call", {"model.profile": "public_fast"}),
    ):
        raise LLMProviderError(
            LLMProviderErrorCode.RATE_LIMIT,
            provider_error_type="RateLimitError",
        )

    span = exporter.get_finished_spans()[0]
    assert span.attributes["error.code"] == "llm_rate_limit"
    assert span.attributes["error.stage"] == "llm_provider"
    assert span.attributes["error.type"] == "RateLimitError"


def test_metric_dimensions_exclude_identifiers_and_free_text() -> None:
    attributes = metric_attributes(
        {
            "run.id": "run-1",
            "mcp.server": "factory",
            "mcp.tool": "get_machine_status",
            "mcp.operation": "READ",
            "operation.status": "success",
            "prompt": "unbounded user text",
        }
    )

    assert attributes == {
        "mcp.server": "factory",
        "mcp.tool": "get_machine_status",
        "mcp.operation": "READ",
        "operation.status": "success",
    }


def test_metric_dimensions_keep_only_bounded_persistence_operation() -> None:
    attributes = metric_attributes(
        {
            "persistence.operation": "complete",
            "operation.status": "success",
            "run.id": "run-1",
            "product_id": "P4711",
            "request_text": "must never be a metric label",
        }
    )

    assert attributes == {
        "persistence.operation": "complete",
        "operation.status": "success",
    }


def test_recovery_lifecycle_metrics_keep_only_bounded_dimensions() -> None:
    telemetry, reader = _metric_telemetry()

    telemetry.record_recovery_lifecycle(
        stage="verification_failed",
        outcome="FAILED",
        verification_status="FAILED",
        classification="CONFIDENTIAL",
    )

    assert _counter_values(reader, "recovery_lifecycle_total") == [
        (
            {
                "recovery.stage": "verification_failed",
                "recovery.outcome": "FAILED",
                "verification.status": "FAILED",
                "data.classification": "CONFIDENTIAL",
            },
            1,
        )
    ]


def test_mcp_reconnect_metric_uses_only_bounded_readiness_dimensions() -> None:
    telemetry, reader = _metric_telemetry()

    telemetry.record_mcp_reconnect(
        attributes={
            "mcp.server": "knowledge",
            "mcp.retry.attempt": 1,
            "mcp.readiness.stage": "discovery",
            "run.profile": "CONFIDENTIAL_TROUBLESHOOTING",
            "run.id": "must-not-be-a-metric-label",
            "error_message": "must-not-be-a-metric-label",
        }
    )

    assert _counter_values(reader, "mcp_reconnect_total") == [
        (
            {
                "mcp.server": "knowledge",
                "mcp.retry.attempt": 1,
                "mcp.readiness.stage": "discovery",
                "run.profile": "CONFIDENTIAL_TROUBLESHOOTING",
            },
            1,
        )
    ]


def test_llm_usage_metrics_aggregate_only_bounded_dimensions() -> None:
    telemetry, reader = _metric_telemetry()
    attributes = {
        "model.profile": "local_quality",
        "data.classification": "RESTRICTED",
        "execution.zone": "LOCAL",
        "operation.status": "success",
        "run.id": "run-123",
        "product_id": "P9001",
        "prompt": "must never become a metric label",
    }

    telemetry.record_llm_usage(
        attributes=attributes,
        input_tokens=11,
        output_tokens=7,
        total_tokens=18,
    )
    telemetry.record_llm_usage(
        attributes=attributes,
        input_tokens=2,
        output_tokens=3,
        total_tokens=5,
    )

    expected_labels = {
        "model.profile": "local_quality",
        "data.classification": "RESTRICTED",
        "execution.zone": "LOCAL",
        "operation.status": "success",
    }
    assert _counter_values(reader, "llm_input_tokens_total") == [(expected_labels, 13)]
    assert _counter_values(reader, "llm_output_tokens_total") == [(expected_labels, 10)]
    assert _counter_values(reader, "llm_total_tokens_total") == [(expected_labels, 23)]


def test_llm_usage_metrics_ignore_missing_partial_and_malformed_values() -> None:
    telemetry, reader = _metric_telemetry()

    telemetry.record_llm_usage(
        attributes={"model.profile": "local_fast"},
        input_tokens=None,
        output_tokens=-1,
        total_tokens=True,  # type: ignore[arg-type]
    )
    telemetry.record_llm_usage(
        attributes={"model.profile": "local_fast"},
        input_tokens=4,
        output_tokens=None,
        total_tokens=None,
    )

    assert _counter_values(reader, "llm_input_tokens_total") == [
        ({"model.profile": "local_fast"}, 4)
    ]
    assert _counter_values(reader, "llm_output_tokens_total") == []
    assert _counter_values(reader, "llm_total_tokens_total") == []


def test_llm_usage_metric_recording_failure_is_ignored() -> None:
    telemetry, _ = _recording_telemetry()

    class _BrokenCounter:
        def add(self, value: int, attributes: object) -> None:
            del value, attributes
            raise OSError("metric exporter unavailable")

    telemetry._llm_input_tokens = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_output_tokens = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_total_tokens = _BrokenCounter()  # type: ignore[assignment]

    telemetry.record_llm_usage(
        attributes={"model.profile": "local_fast"},
        input_tokens=11,
        output_tokens=7,
        total_tokens=18,
    )


def test_attribute_allowlist_drops_tool_results_tokens_and_unknown_values() -> None:
    attributes = safe_attributes(
        {
            "mcp.server": "factory",
            "error.stage": "final_output_normalization",
            "tool_result": "sensitive data",
            "bearer_token": "secret",
            "unknown.attribute": "not governed",
        }
    )

    assert attributes == {
        "mcp.server": "factory",
        "error.stage": "final_output_normalization",
    }


def test_mcp_http_hook_injects_w3c_context_without_changing_authorization() -> None:
    telemetry, _ = _recording_telemetry()
    client = _HookClient()
    request = _HookRequest(
        headers={
            "Authorization": "Bearer unchanged",
            "baggage": "clearance=forged",
            "traceparent": "00-00000000000000000000000000000001-0000000000000001-01",
            "tracestate": "vendor=forged",
        }
    )
    token = attach(
        baggage.set_baggage(
            "identity",
            "forged",
            trace.set_span_in_context(
                NonRecordingSpan(
                    SpanContext(
                        trace_id=0x4BF92F3577B34DA6A3CE929D0E0E4736,
                        span_id=0x00F067AA0BA902B7,
                        is_remote=False,
                        trace_flags=TraceFlags(TraceFlags.SAMPLED),
                        trace_state=TraceState([("vendor", "state")]),
                    )
                )
            ),
        )
    )
    try:
        instrument_mcp_http_client(client, telemetry)
        asyncio.run(client.event_hooks["request"][0](request))
    finally:
        detach(token)

    assert request.headers["Authorization"] == "Bearer unchanged"
    assert request.headers["traceparent"] == (
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    )
    assert request.headers["tracestate"] == "vendor=state"
    assert "baggage" not in request.headers


def test_w3c_extraction_keeps_parent_trace_and_malformed_context_is_safe() -> None:
    parent = propagate.extract(
        {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    )
    malformed = propagate.extract({"traceparent": "not-a-traceparent"})

    assert (
        trace.get_current_span(parent).get_span_context().trace_id
        == 0x4BF92F3577B34DA6A3CE929D0E0E4736
    )
    assert trace.get_current_span(malformed).get_span_context().is_valid is False


def test_mcp_asgi_boundary_uses_the_w3c_parent_context() -> None:
    telemetry, exporter = _recording_telemetry()

    async def endpoint(request: Request) -> JSONResponse:
        context = trace.get_current_span().get_span_context()
        return JSONResponse({"trace_id": f"{context.trace_id:032x}"})

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
    instrument_mcp_http_app(app, telemetry)

    async def request_app() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp",
                headers={
                    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-"
                    "00f067aa0ba902b7-01"
                },
            )
        return response.json()["trace_id"]

    assert asyncio.run(request_app()) == "4bf92f3577b34da6a3ce929d0e0e4736"
    server_spans = [
        span
        for span in exporter.get_finished_spans()
        if span.context.trace_id == 0x4BF92F3577B34DA6A3CE929D0E0E4736
    ]
    assert server_spans
    assert any(
        span.parent is not None and span.parent.span_id == 0x00F067AA0BA902B7
        for span in server_spans
    )


def test_mcp_asgi_boundary_starts_a_trace_when_context_is_missing() -> None:
    telemetry, exporter = _recording_telemetry()

    async def endpoint(request: Request) -> JSONResponse:
        del request
        context = trace.get_current_span().get_span_context()
        return JSONResponse({"trace_id": f"{context.trace_id:032x}"})

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
    instrument_mcp_http_app(app, telemetry)

    async def request_app() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post("/mcp")
        return response.json()["trace_id"]

    trace_id = asyncio.run(request_app())

    assert trace_id != "0" * 32
    assert any(
        f"{span.context.trace_id:032x}" == trace_id
        for span in exporter.get_finished_spans()
    )


def test_mcp_http_client_and_server_continue_one_w3c_trace() -> None:
    client_telemetry, client_exporter = _recording_telemetry(
        service_name="industrial-ai-agent"
    )
    server_telemetry, server_exporter = _recording_telemetry(
        service_name="knowledge-mcp"
    )

    async def endpoint(request: Request) -> JSONResponse:
        del request
        context = trace.get_current_span().get_span_context()
        return JSONResponse({"trace_id": f"{context.trace_id:032x}"})

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
    instrument_mcp_http_app(app, server_telemetry)

    async def request_app() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            instrument_mcp_http_client(client, client_telemetry)
            response = await client.post("/mcp")
        return response.json()["trace_id"]

    with client_telemetry.span(
        "mcp.tool", {"mcp.tool": "search_documentation"}
    ) as span:
        trace_id = asyncio.run(request_app())
        client_span_context = span.get_span_context()

    server_spans = server_exporter.get_finished_spans()
    assert trace_id == f"{client_span_context.trace_id:032x}"
    assert any(
        server_span.parent is not None
        and server_span.parent.span_id == client_span_context.span_id
        and server_span.context.trace_id == client_span_context.trace_id
        for server_span in server_spans
    )
    assert client_exporter.get_finished_spans()[0].resource.attributes[
        SERVICE_NAME
    ] == ("industrial-ai-agent")
    assert all(
        span.resource.attributes[SERVICE_NAME] == "knowledge-mcp"
        for span in server_spans
    )


def test_mcp_asgi_boundary_ignores_malformed_context() -> None:
    telemetry, exporter = _recording_telemetry()

    async def endpoint(request: Request) -> JSONResponse:
        del request
        context = trace.get_current_span().get_span_context()
        return JSONResponse({"trace_id": f"{context.trace_id:032x}"})

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
    instrument_mcp_http_app(app, telemetry)

    async def request_app() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp",
                headers={"traceparent": "not-a-traceparent", "baggage": "role=admin"},
            )
        return response.json()["trace_id"]

    trace_id = asyncio.run(request_app())

    assert trace_id != "0" * 32
    assert all(
        f"{span.context.trace_id:032x}" == trace_id
        for span in exporter.get_finished_spans()
    )


def test_disabled_telemetry_does_not_add_mcp_http_hook() -> None:
    client = _HookClient()

    instrument_mcp_http_client(client, Telemetry(TelemetryConfiguration(enabled=False)))

    assert client.event_hooks["request"] == []


def test_maintenance_span_is_emitted_only_for_the_actual_tool_invocation() -> None:
    telemetry, exporter = _recording_telemetry()

    class Client:
        async def call_tool(
            self, name: str, arguments: dict[str, object]
        ) -> CallToolResult:
            assert name == "create_maintenance_ticket"
            assert arguments["station_id"] == "S04"
            return CallToolResult(content=[], structuredContent={"ticket_id": "MT-1"})

    tool = _create_langchain_tool(
        Tool(
            name="create_maintenance_ticket",
            description="Create a maintenance ticket.",
            inputSchema={
                "type": "object",
                "properties": {
                    "station_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "request_id": {"type": "string"},
                },
                "required": ["station_id", "summary", "request_id"],
                "additionalProperties": False,
            },
        ),
        Client(),
        server_id="factory",
        operation="write",
        telemetry=telemetry,
    )

    asyncio.run(
        tool.ainvoke(
            {
                "station_id": "S04",
                "summary": "private ticket content",
                "request_id": "ticket-call-1",
            }
        )
    )

    spans = exporter.get_finished_spans()
    maintenance_spans = [
        span for span in spans if span.name == "maintenance_ticket.create"
    ]
    assert len(maintenance_spans) == 1
    assert "summary" not in maintenance_spans[0].attributes
    assert "private ticket content" not in str(maintenance_spans[0].attributes)


def _recording_telemetry(
    *, service_name: str = "industrial-ai-agent"
) -> tuple[Telemetry, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name})
    )
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True, service_name=service_name),
        tracer_provider=tracer_provider,
        meter_provider=MeterProvider(),
    )
    return telemetry, exporter


def _metric_telemetry() -> tuple[Telemetry, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True),
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    return telemetry, reader


def _counter_values(
    reader: InMemoryMetricReader, metric_name: str
) -> list[tuple[dict[str, object], int | float]]:
    values: list[tuple[dict[str, object], int | float]] = []
    for resource_metric in reader.get_metrics_data().resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name != metric_name:
                    continue
                for point in metric.data.data_points:
                    values.append((dict(point.attributes), point.value))
    return values


class _HookClient:
    def __init__(self) -> None:
        self.event_hooks: dict[str, list[object]] = {"request": []}


class _HookRequest:
    def __init__(self, *, headers: dict[str, str]) -> None:
        self.headers = headers
