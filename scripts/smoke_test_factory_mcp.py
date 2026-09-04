"""Run a local stdio MCP discovery and read-only tool-call smoke test."""

import asyncio
import json
import sys

from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.infrastructure.factory_mcp_client import run_factory_mcp_smoke


def main() -> None:
    result = asyncio.run(
        run_factory_mcp_smoke(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
            )
        )
    )
    print(f"Server: {result.server_name} {result.server_version}")
    print(f"Protocol version: {result.protocol_version}")
    print(f"Discovered tools: {', '.join(result.tool_names)}")
    print("get_product_history(P4711):")
    print(json.dumps(result.product_history, indent=2, sort_keys=True))
    print("get_machine_status(S04):")
    print(json.dumps(result.machine_status, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
