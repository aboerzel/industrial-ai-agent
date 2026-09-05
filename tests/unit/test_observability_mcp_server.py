from __future__ import annotations

import asyncio
import inspect

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from industrial_ai_agent.infrastructure.observability_mcp_server import (
    OBSERVABILITY_MCP_SERVER_NAME,
    create_observability_mcp_server,
)

RUN_ID = "123e4567-e89b-12d3-a456-426614174000"
TRACE_ID = "0123456789abcdef0123456789abcdef"


def test_observability_mcp_exposes_only_bounded_read_only_tools() -> None:
    server = create_observability_mcp_server(evidence_service=_FakeEvidenceService())  # type: ignore[arg-type]
    tools = asyncio.run(server.list_tools())

    assert OBSERVABILITY_MCP_SERVER_NAME == "observability_mcp"
    assert {tool.name for tool in tools} == {
        "get_run_trace",
        "get_trace_logs",
        "get_run_metrics",
        "get_service_health",
        "investigate_run",
    }
    assert all(tool.annotations.read_only_hint for tool in tools)
    assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
    schemas = {tool.name: tool.input_schema for tool in tools}
    assert "query" not in schemas["get_run_trace"]["properties"]
    assert "promql" not in schemas["get_service_health"]["properties"]
    assert "logql" not in schemas["get_trace_logs"]["properties"]
    assert "traceql" not in schemas["get_run_trace"]["properties"]


def test_observability_mcp_validates_identifiers_before_backend_dispatch() -> None:
    evidence = _FakeEvidenceService()
    server = create_observability_mcp_server(evidence_service=evidence)  # type: ignore[arg-type]

    async def call_invalid() -> None:
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool("get_run_trace", {"run_id": "arbitrary TraceQL"})
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool("get_trace_logs", {"trace_id": "{ status = error }"})

    asyncio.run(call_invalid())
    assert evidence.calls == []


def test_investigate_run_is_a_deterministic_adapter_not_agent_or_write_path() -> None:
    source = inspect.getsource(create_observability_mcp_server)
    assert "LangGraph" not in source
    assert "create_maintenance_ticket" not in source

    server = create_observability_mcp_server(evidence_service=_FakeEvidenceService())  # type: ignore[arg-type]

    async def call() -> dict[str, object]:
        result = await server.call_tool("investigate_run", {"run_id": RUN_ID})
        assert isinstance(result, CallToolResult)
        return result.structured_content

    result = asyncio.run(call())
    assert result["run_id"] == RUN_ID
    assert "not a root-cause conclusion" in result["limitations"][0]


class _FakeEvidenceService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_run_trace(self, run_id: str):
        self.calls.append("get_run_trace")
        return _Model({"run_id": run_id, "trace_id": TRACE_ID, "spans": []})

    def get_trace_logs(self, trace_id: str, service_name: str | None):
        self.calls.append("get_trace_logs")
        return ()

    def get_run_metrics(self, identifier: str):
        self.calls.append("get_run_metrics")
        return _Model({"source": "trace_correlated_window", "series": []})

    def get_service_health(self, service_name: str, time_window: str):
        self.calls.append("get_service_health")
        return _Model({"source": "service_health_window", "series": []})

    def investigate_run(self, run_id: str) -> dict[str, object]:
        self.calls.append("investigate_run")
        return {
            "run_id": run_id,
            "trace_id": TRACE_ID,
            "status": "error",
            "failure_stage": "mcp.discovery",
            "failing_service": "factory-mcp",
            "failing_operation": "mcp.discovery",
            "error_code": "McpUnavailable",
            "timeline": [],
            "correlated_logs": [],
            "metric_context": {},
            "evidence": ["An error span identifies the failure location."],
            "limitations": ["This is deterministic evidence aggregation, not a root-cause conclusion."],
        }


class _Model:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self._value
