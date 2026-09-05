"""Exercise the authenticated, read-only Observability MCP against a known run."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
    open_mcp_session,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def _run(run_id: str) -> None:
    token = os.getenv("MCP_CODEX_DEVELOPMENT_TOKEN")
    if not token:
        raise RuntimeError("MCP_CODEX_DEVELOPMENT_TOKEN must be configured")
    async with open_mcp_session(
        StreamableHttpServerParameters(
            url="http://127.0.0.1:8003/mcp", bearer_token=token
        )
    ) as session:
        await session.initialize()
        tools = await session.list_tools()
        trace = await session.call_tool("get_run_trace", {"run_id": run_id})
        trace_id = trace.structured_content["trace_id"]
        logs = await session.call_tool("get_trace_logs", {"trace_id": trace_id})
        metrics = await session.call_tool("get_run_metrics", {"run_or_trace_id": run_id})
        health = await session.call_tool(
            "get_service_health",
            {"service_name": "industrial-ai-agent", "time_window": "15m"},
        )
        investigation = await session.call_tool("investigate_run", {"run_id": run_id})

    expected = {
        "get_run_trace",
        "get_trace_logs",
        "get_run_metrics",
        "get_service_health",
        "investigate_run",
    }
    actual = {tool.name for tool in tools.tools}
    if actual != expected:
        raise RuntimeError(f"Unexpected read-only tool surface: {sorted(actual)}")
    if not isinstance(trace_id, str):
        raise TypeError("get_run_trace did not return a trace ID")
    if not isinstance(logs.structured_content.get("events"), list):
        raise TypeError("get_trace_logs did not return structured events")
    if not isinstance(metrics.structured_content.get("series"), list):
        raise TypeError("get_run_metrics did not return bounded metric series")
    if not isinstance(health.structured_content.get("series"), list):
        raise TypeError("get_service_health did not return bounded metric series")
    if investigation.structured_content.get("trace_id") != trace_id:
        raise RuntimeError("investigate_run did not retain the trace correlation")

    print("SUCCESS")
    print(f"run_id={run_id}")
    print(f"trace_id={trace_id}")
    print(f"status={trace.structured_content.get('status')}")
    print(f"visible_tools={','.join(sorted(actual))}")
    print(f"failure_stage={investigation.structured_content.get('failure_stage')}")
    print(f"failing_service={investigation.structured_content.get('failing_service')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    args = parser.parse_args()
    load_local_environment(PROJECT_ROOT / ".env")
    asyncio.run(_run(args.run_id))


if __name__ == "__main__":
    main()
