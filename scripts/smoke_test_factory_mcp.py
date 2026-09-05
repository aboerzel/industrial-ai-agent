"""Run a factory MCP discovery and read-only tool-call smoke test."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    FactoryMcpTransport,
    StreamableHttpServerParameters,
    run_factory_mcp_smoke,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_local_environment(PROJECT_ROOT / ".env")
    args = _parse_args()
    result = asyncio.run(run_factory_mcp_smoke(_transport_from_args(args)))
    print(f"Server: {result.server_name} {result.server_version}")
    print(f"Protocol version: {result.protocol_version}")
    print(f"Discovered tools: {', '.join(result.tool_names)}")
    print("get_product_history(P4711):")
    print(json.dumps(result.product_history, indent=2, sort_keys=True))
    print("get_machine_status(S04):")
    print(json.dumps(result.machine_status, indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a factory MCP smoke test.")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8001/mcp")
    return parser.parse_args()


def _transport_from_args(args: argparse.Namespace) -> FactoryMcpTransport:
    if args.transport == "http":
        return StreamableHttpServerParameters(
            url=args.mcp_url,
            bearer_token=_required_industrial_agent_token(),
        )
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
    )


def _required_industrial_agent_token() -> str:
    token = os.getenv("MCP_INDUSTRIAL_AGENT_TOKEN")
    if not token:
        raise RuntimeError("MCP_INDUSTRIAL_AGENT_TOKEN must be configured")
    return token


if __name__ == "__main__":
    main()
