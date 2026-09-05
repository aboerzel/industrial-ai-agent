from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.types import CallToolResult, Tool
from opentelemetry import propagate, trace
from opentelemetry.context import attach, detach
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

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


def test_attribute_allowlist_drops_tool_results_tokens_and_unknown_values() -> None:
    attributes = safe_attributes(
        {
            "mcp.server": "factory",
            "tool_result": "sensitive data",
            "bearer_token": "secret",
            "unknown.attribute": "not governed",
        }
    )

    assert attributes == {"mcp.server": "factory"}


def test_mcp_http_hook_injects_w3c_context_without_changing_authorization() -> None:
    telemetry, _ = _recording_telemetry()
    client = _HookClient()
    request = _HookRequest(headers={"Authorization": "Bearer unchanged"})
    token = attach(
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


def _recording_telemetry() -> tuple[Telemetry, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True),
        tracer_provider=tracer_provider,
        meter_provider=MeterProvider(),
    )
    return telemetry, exporter


class _HookClient:
    def __init__(self) -> None:
        self.event_hooks: dict[str, list[object]] = {"request": []}


class _HookRequest:
    def __init__(self, *, headers: dict[str, str]) -> None:
        self.headers = headers
