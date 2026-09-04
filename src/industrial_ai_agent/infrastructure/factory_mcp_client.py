"""Official-SDK client path for the local factory MCP server."""

from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@dataclass(frozen=True)
class FactoryMcpSmokeResult:
    """Protocol discovery and structured results returned by a factory MCP server."""

    server_name: str
    server_version: str
    protocol_version: str
    tool_names: tuple[str, ...]
    product_history: dict[str, Any] | None
    machine_status: dict[str, Any] | None


async def run_factory_mcp_smoke(
    server_parameters: StdioServerParameters,
) -> FactoryMcpSmokeResult:
    """Discover and call the two read-only tools through an MCP stdio session."""
    async with (
        stdio_client(server_parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        listed_tools = await session.list_tools()
        product_history = await session.call_tool(
            "get_product_history", {"product_id": "P4711"}
        )
        machine_status = await session.call_tool(
            "get_machine_status", {"station_id": "S04"}
        )

    return FactoryMcpSmokeResult(
        server_name=initialized.server_info.name,
        server_version=initialized.server_info.version,
        protocol_version=initialized.protocol_version,
        tool_names=tuple(tool.name for tool in listed_tools.tools),
        product_history=product_history.structured_content,
        machine_status=machine_status.structured_content,
    )
