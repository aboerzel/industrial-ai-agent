"""Run a knowledge MCP discovery and structured search smoke test."""

import argparse
import asyncio
import json
import sys

from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    McpTransport,
    StreamableHttpServerParameters,
    open_mcp_session,
)

SMOKE_QUERY = "E-STOP-17 emergency stop at station S04"


async def run_smoke(transport: McpTransport) -> dict[str, object]:
    """Discover the only knowledge tool and call it through one MCP session."""
    async with open_mcp_session(transport) as session:
        initialized = await session.initialize()
        listed_tools = await session.list_tools()
        response = await session.call_tool(
            "search_documentation",
            {"query": SMOKE_QUERY, "top_k": 3},
        )
    if response.structured_content is None:
        raise RuntimeError("Knowledge MCP search did not return structured content")
    result = dict(response.structured_content)
    results = result.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError("Knowledge MCP search did not return documentation results")
    return {
        "server": f"{initialized.server_info.name} {initialized.server_info.version}",
        "protocol": initialized.protocol_version,
        "tools": [tool.name for tool in listed_tools.tools],
        "result": result,
    }


def main() -> None:
    args = _parse_args()
    result = asyncio.run(run_smoke(_transport_from_args(args)))
    print(f"Server: {result['server']}")
    print(f"Protocol version: {result['protocol']}")
    print(f"Discovered tools: {', '.join(result['tools'])}")
    print(json.dumps(result["result"], indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a knowledge MCP smoke test.")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8002/mcp")
    return parser.parse_args()


def _transport_from_args(args: argparse.Namespace) -> McpTransport:
    if args.transport == "http":
        return StreamableHttpServerParameters(url=args.mcp_url)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.knowledge_mcp_server"],
    )


if __name__ == "__main__":
    main()
