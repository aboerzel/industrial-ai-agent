"""Protocol-aware readiness checks for Streamable HTTP MCP servers."""

import argparse
import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass

from industrial_ai_agent.infrastructure.factory_mcp_client import (
    McpTransport,
    StreamableHttpServerParameters,
    open_mcp_session,
)


@dataclass(frozen=True, slots=True)
class McpReadinessResult:
    """The bounded MCP capabilities confirmed by one readiness probe."""

    server_name: str
    tool_names: tuple[str, ...]


class McpReadinessError(RuntimeError):
    """The server process is reachable but cannot satisfy its MCP contract."""


async def probe_mcp_readiness(
    transport: McpTransport,
    *,
    required_tool_names: Iterable[str] = (),
) -> McpReadinessResult:
    """Require MCP initialization and bounded tool discovery before readiness."""
    required = frozenset(required_tool_names)
    async with open_mcp_session(transport) as session:
        initialized = await session.initialize()
        listed_tools = await session.list_tools()

    tool_names = tuple(tool.name for tool in listed_tools.tools)
    missing = required.difference(tool_names)
    if missing:
        raise McpReadinessError("Required MCP capabilities are unavailable")
    return McpReadinessResult(
        server_name=initialized.server_info.name,
        tool_names=tool_names,
    )


def main() -> None:
    """Run a silent Docker-healthcheck-safe MCP readiness probe."""
    parser = argparse.ArgumentParser(description="Probe Streamable HTTP MCP readiness.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--bearer-token-env", required=True)
    parser.add_argument("--required-tool", action="append", default=[])
    args = parser.parse_args()

    token = os.getenv(args.bearer_token_env)
    if token is None or not token.strip():
        raise SystemExit(1)
    try:
        asyncio.run(
            probe_mcp_readiness(
                StreamableHttpServerParameters(url=args.url, bearer_token=token),
                required_tool_names=args.required_tool,
            )
        )
    except Exception:  # noqa: BLE001 - Docker health checks must not expose internals.
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
