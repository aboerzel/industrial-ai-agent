from __future__ import annotations

import asyncio

import pytest
from mcp.types import CallToolResult, Tool
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    _create_langchain_tool,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    configure_telemetry,
    metric_attributes,
    safe_attributes,
)


def test_disabled_bootstrap_is_safe_without_a_collector() -> None:
    telemetry = configure_telemetry(TelemetryConfiguration(enabled=False))

    with telemetry.span("agent.run", {"run.id": "run-1"}):
        pass

    assert telemetry.enabled is False


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
