"""Read-only MCP transport for bounded observability root-cause evidence."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from time import perf_counter
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import StringConstraints

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.infrastructure.mcp_access_control import (
    McpHttpAccessControl,
    create_demo_mcp_access_control,
    install_mcp_http_access_control,
)
from industrial_ai_agent.infrastructure.mcp_schema_validation import (
    require_strict_mcp_tool_arguments,
)
from industrial_ai_agent.infrastructure.observability_backends import (
    BackendConfiguration,
    LokiAdapter,
    ObservabilityEvidenceService,
    PrometheusAdapter,
    TempoAdapter,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    configure_telemetry,
    run_instrumented_mcp_http_server,
    sanitized_error_code,
)

OBSERVABILITY_MCP_SERVER_NAME = "observability_mcp"
OBSERVABILITY_MCP_SERVER_VERSION = "0.1.0"
OBSERVABILITY_MCP_HTTP_PATH = "/mcp"

RunIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    ),
]
TraceIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9a-fA-F]{32}$")
]
ServiceName = Literal[
    "industrial-ai-agent", "factory-mcp", "knowledge-mcp", "observability-mcp"
]
ServiceHealthWindow = Literal["5m", "15m", "1h"]

_OBSERVABILITY_TOOL_PERMISSIONS = {
    "get_run_trace": McpPermission.READ_OBSERVABILITY,
    "get_trace_logs": McpPermission.READ_OBSERVABILITY,
    "get_run_metrics": McpPermission.READ_OBSERVABILITY,
    "get_service_health": McpPermission.READ_OBSERVABILITY,
    "investigate_run": McpPermission.READ_OBSERVABILITY,
}


def create_observability_mcp_server(
    *,
    evidence_service: ObservabilityEvidenceService,
    access_control: McpHttpAccessControl | None = None,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Expose the fixed observability evidence surface through MCP SDK v2."""
    server = MCPServer(
        name=OBSERVABILITY_MCP_SERVER_NAME,
        version=OBSERVABILITY_MCP_SERVER_VERSION,
        description="Read-only bounded trace, log, and metric evidence for RCA.",
    )

    @server.tool(
        name="get_run_trace",
        description="Retrieve safe distributed trace metadata for one agent run UUID.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_run_trace(run_id: RunIdentifier, ctx: Context | None = None) -> dict[str, Any]:
        _authorize(ctx, access_control, "get_run_trace")
        return _invoke_tool(
            telemetry, "get_run_trace", lambda: evidence_service.get_run_trace(run_id).model_dump(mode="json")
        )

    @server.tool(
        name="get_trace_logs",
        description="Retrieve metadata-only Loki events correlated with one trace ID.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_trace_logs(
        trace_id: TraceIdentifier,
        service_name: ServiceName | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        _authorize(ctx, access_control, "get_trace_logs")
        return _invoke_tool(
            telemetry,
            "get_trace_logs",
            lambda: {
                "trace_id": trace_id.lower(),
                "events": [
                    event.model_dump(mode="json")
                    for event in evidence_service.get_trace_logs(trace_id, service_name)
                ],
            },
        )

    @server.tool(
        name="get_run_metrics",
        description="Retrieve bounded Prometheus context for a run UUID or trace ID, never per-run metric labels.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_run_metrics(
        run_or_trace_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        _authorize(ctx, access_control, "get_run_metrics")
        return _invoke_tool(
            telemetry,
            "get_run_metrics",
            lambda: evidence_service.get_run_metrics(run_or_trace_id).model_dump(mode="json"),
        )

    @server.tool(
        name="get_service_health",
        description="Retrieve bounded operational health for a known service and fixed time window.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_service_health(
        service_name: ServiceName,
        time_window: ServiceHealthWindow = "15m",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        _authorize(ctx, access_control, "get_service_health")
        return _invoke_tool(
            telemetry,
            "get_service_health",
            lambda: {
                "service_name": service_name,
                "time_window": time_window,
                **evidence_service.get_service_health(service_name, time_window).model_dump(mode="json"),
            },
        )

    @server.tool(
        name="investigate_run",
        description="Deterministically aggregate bounded RCA evidence for one run UUID; it does not infer a root cause.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def investigate_run(run_id: RunIdentifier, ctx: Context | None = None) -> dict[str, Any]:
        _authorize(ctx, access_control, "investigate_run")
        return _invoke_tool(telemetry, "investigate_run", lambda: evidence_service.investigate_run(run_id))

    for tool_name in _OBSERVABILITY_TOOL_PERMISSIONS:
        require_strict_mcp_tool_arguments(server, tool_name)
    if access_control is not None:
        install_mcp_http_access_control(server, access_control)
    return server


def create_default_observability_mcp_server(
    *, telemetry: Telemetry | None = None
) -> MCPServer:
    """Assemble only infrastructure query adapters; no agent runtime is involved."""
    configuration = BackendConfiguration(
        tempo_url=os.getenv("TEMPO_URL", "http://127.0.0.1:3200"),
        loki_url=os.getenv("LOKI_URL", "http://127.0.0.1:3100"),
        prometheus_url=os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090"),
        timeout_seconds=float(os.getenv("OBSERVABILITY_BACKEND_TIMEOUT_SECONDS", "2")),
    )
    return create_observability_mcp_server(
        evidence_service=_create_evidence_service(configuration), telemetry=telemetry
    )


def create_secure_observability_mcp_server(
    *, telemetry: Telemetry | None = None
) -> MCPServer:
    """Assemble authenticated HTTP MCP with ADR-015 identity resolution."""
    configuration = BackendConfiguration(
        tempo_url=os.getenv("TEMPO_URL", "http://tempo:3200"),
        loki_url=os.getenv("LOKI_URL", "http://loki:3100"),
        prometheus_url=os.getenv("PROMETHEUS_URL", "http://prometheus:9090"),
        timeout_seconds=float(os.getenv("OBSERVABILITY_BACKEND_TIMEOUT_SECONDS", "2")),
    )
    evidence_service = _create_evidence_service(configuration)
    server: MCPServer

    async def listed_tools():
        return await server.list_tools()

    access_control = create_demo_mcp_access_control(
        tools=listed_tools,
        required_permission=lambda tool_name: _OBSERVABILITY_TOOL_PERMISSIONS[tool_name],
    )
    server = create_observability_mcp_server(
        evidence_service=evidence_service,
        access_control=access_control,
        telemetry=telemetry,
    )
    return server


def main() -> None:
    """Start a stdio development server or the authenticated HTTP deployment service."""
    args = _parse_args()
    telemetry = _create_telemetry() if args.transport != "stdio" else None
    server = (
        create_default_observability_mcp_server(telemetry=telemetry)
        if args.transport == "stdio"
        else create_secure_observability_mcp_server(telemetry=telemetry)
    )
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    assert telemetry is not None
    run_instrumented_mcp_http_server(
        server,
        host=args.host,
        port=args.port,
        streamable_http_path=OBSERVABILITY_MCP_HTTP_PATH,
        telemetry=telemetry,
    )


def _create_evidence_service(configuration: BackendConfiguration) -> ObservabilityEvidenceService:
    timeout = httpx.Timeout(configuration.timeout_seconds)
    return ObservabilityEvidenceService(
        tempo=TempoAdapter(configuration.tempo_url, client=httpx.Client(timeout=timeout)),
        loki=LokiAdapter(configuration.loki_url, client=httpx.Client(timeout=timeout)),
        prometheus=PrometheusAdapter(configuration.prometheus_url, client=httpx.Client(timeout=timeout)),
    )


def _authorize(
    ctx: Context | None, access_control: McpHttpAccessControl | None, tool_name: str
) -> None:
    if access_control is None:
        return
    if ctx is None:
        raise PermissionError("MCP authentication failed")
    access_control.authorize_tool(access_control.access_context_from_headers(ctx.headers), tool_name)


def _invoke_tool(telemetry: Telemetry | None, tool_name: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if telemetry is None:
        return action()
    started = perf_counter()
    status = "success"
    attributes = {"mcp.tool": tool_name, "mcp.operation": "read", "operation.type": "read"}
    try:
        with telemetry.span("observability.query", attributes):
            result = action()
        telemetry.log_event(event="mcp.server.completed", run_id=None)
        return result
    except BaseException as error:
        status = "failure"
        telemetry.log_error(event="mcp.server.failed", run_id=None, error_code=sanitized_error_code(error))
        raise
    finally:
        telemetry.record_mcp_call(
            attributes={**attributes, "operation.status": status},
            duration_seconds=perf_counter() - started,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the read-only Observability MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("OBSERVABILITY_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("OBSERVABILITY_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("OBSERVABILITY_MCP_PORT", "8003")))
    return parser.parse_args()


def _create_telemetry() -> Telemetry:
    return configure_telemetry(
        TelemetryConfiguration(
            enabled=os.getenv("OTEL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "127.0.0.1:4317"),
            service_name=os.getenv("OTEL_SERVICE_NAME", "observability-mcp"),
        )
    )


if __name__ == "__main__":
    main()
